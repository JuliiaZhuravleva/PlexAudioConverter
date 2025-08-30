#!/usr/bin/env python3
"""
Plex Audio Converter - Автоматическая конвертация 5.1 в стерео
Решение проблемы воспроизведения многоканального звука на AndroidTV

Автор: Assistant
Версия: 1.0
"""

import os
import sys
import json
import logging
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import time
import shutil

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audio_converter.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
CONFIG = {
    'video_extensions': ['.mp4', '.mkv', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.webm'],
    'max_depth': 2,  # Максимальная глубина вложенности папок
    'tech_file': '.audio_converter_state.json',  # Технический файл состояния
    'backup_suffix': '_original',  # Суффикс для резервных копий
    'ffmpeg_path': 'ffmpeg',  # Путь к ffmpeg (можно указать полный путь)
    'ffprobe_path': 'ffprobe',  # Путь к ffprobe

    # Параметры конвертации
    'audio_codec': 'aac',  # Кодек для стерео дорожки
    'audio_bitrate': '192k',  # Битрейт для стерео
    'audio_sample_rate': '48000',  # Частота дискретизации

    # Формула downmix с усилением центрального канала для диалогов
    # Основано на рекомендациях из документации ffmpeg и сообщества Plex
    'downmix_formula': 'pan=stereo|FL=1.414*FC+0.707*FL+0.5*BL+0.5*SL+0.25*LFE+0.125*BR|FR=1.414*FC+0.707*FR+0.5*BR+0.5*SR+0.25*LFE+0.125*BL',

    # Нормализация громкости (loudnorm для ночного режима)
    'use_loudnorm': True,
    'loudnorm_params': 'loudnorm=I=-23:TP=-2:LRA=7'
}


class AudioTrack:
    """Класс для представления аудио дорожки"""

    def __init__(self, index: int, codec: str, channels: int, language: str, title: str = None):
        self.index = index
        self.codec = codec
        self.channels = channels
        self.language = language
        self.title = title or ""

    def is_stereo(self) -> bool:
        return self.channels == 2

    def is_surround(self) -> bool:
        return self.channels > 2

    def __str__(self) -> str:
        return f"Track {self.index}: {self.language} {self.codec} {self.channels}ch {self.title}"


class VideoFileProcessor:
    """Основной класс для обработки видеофайлов"""

    def __init__(self, config: Dict):
        self.config = config
        self.state_file = None
        self.state_data = {}

    def load_state(self, directory: Path) -> Dict:
        """Загрузка состояния из технического файла"""
        state_file = directory / self.config['tech_file']
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Не удалось загрузить состояние из {state_file}: {e}")
        return {}

    def save_state(self, directory: Path, state: Dict):
        """Сохранение состояния в технический файл"""
        state_file = directory / self.config['tech_file']
        try:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Не удалось сохранить состояние в {state_file}: {e}")

    def get_audio_tracks(self, file_path: Path) -> List[AudioTrack]:
        """Получение информации об аудио дорожках"""
        tracks = []
        try:
            cmd = [
                self.config['ffprobe_path'],
                '-v', 'error',
                '-print_format', 'json',
                '-show_streams',
                '-select_streams', 'a',
                str(file_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                streams = data.get('streams', [])

                for stream in streams:
                    index = stream.get('index', -1)
                    codec = stream.get('codec_name', 'unknown')
                    channels = stream.get('channels', 0)

                    # Определение языка
                    tags = stream.get('tags', {})
                    language = tags.get('language', 'und')
                    title = tags.get('title', '')

                    track = AudioTrack(index, codec, channels, language, title)
                    tracks.append(track)

        except Exception as e:
            logger.error(f"Ошибка при анализе {file_path}: {e}")

        return tracks

    def find_english_tracks(self, tracks: List[AudioTrack]) -> Tuple[Optional[AudioTrack], Optional[AudioTrack]]:
        """Поиск английских дорожек (стерео и 5.1)"""
        eng_stereo = None
        eng_surround = None

        for track in tracks:
            # Проверяем английский язык (eng, en, english)
            is_english = track.language.lower() in ['eng', 'en', 'english'] or \
                         'eng' in track.title.lower() or \
                         'english' in track.title.lower()

            if is_english:
                if track.is_stereo() and not eng_stereo:
                    eng_stereo = track
                elif track.is_surround() and not eng_surround:
                    eng_surround = track

        # Если не нашли по языку, берем первые подходящие дорожки
        if not eng_stereo and not eng_surround:
            for track in tracks:
                if track.is_stereo() and not eng_stereo:
                    eng_stereo = track
                elif track.is_surround() and not eng_surround:
                    eng_surround = track

        return eng_stereo, eng_surround

    def convert_audio(self, input_file: Path, output_file: Path,
                      surround_track: AudioTrack, keep_original: bool = True) -> bool:
        """Конвертация 5.1 в стерео"""
        try:
            # Формируем команду ffmpeg
            cmd = [
                self.config['ffmpeg_path'],
                '-i', str(input_file),
                '-map', '0:v',  # Копируем видео
                '-c:v', 'copy',  # Без перекодирования видео
            ]

            # Добавляем новую стерео дорожку
            audio_filter = self.config['downmix_formula']
            if self.config['use_loudnorm']:
                audio_filter += f",{self.config['loudnorm_params']}"

            cmd.extend([
                '-map', f'0:{surround_track.index}',
                '-c:a:0', self.config['audio_codec'],
                '-ac:a:0', '2',  # Стерео
                '-b:a:0', self.config['audio_bitrate'],
                '-ar:a:0', self.config['audio_sample_rate'],
                '-filter:a:0', audio_filter,
                '-metadata:s:a:0', 'title=English 2.0 Stereo (Converted)',
                '-metadata:s:a:0', 'language=eng',
            ])

            # Копируем остальные потоки (субтитры и т.д.)
            cmd.extend([
                '-map', '0:s?',  # Субтитры (если есть)
                '-c:s', 'copy',
                '-map_metadata', '0',  # Копируем метаданные
                '-y',  # Перезаписать выходной файл
                str(output_file)
            ])

            logger.info(f"Начинаем конвертацию: {input_file.name}")
            logger.debug(f"Команда: {' '.join(cmd)}")

            # Выполняем конвертацию
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

            if result.returncode == 0:
                logger.info(f"✅ Успешно конвертирован: {input_file.name}")

                # Проверяем размер выходного файла
                if output_file.exists() and output_file.stat().st_size > 1000:
                    if not keep_original:
                        # Создаем резервную копию оригинала
                        backup_file = input_file.with_suffix(f'{self.config["backup_suffix"]}{input_file.suffix}')
                        shutil.move(str(input_file), str(backup_file))
                        logger.info(f"Оригинал сохранен как: {backup_file.name}")

                        # Переименовываем новый файл
                        shutil.move(str(output_file), str(input_file))
                        logger.info(f"Файл заменен на конвертированную версию")

                    return True
                else:
                    logger.error(f"Выходной файл пустой или не создан")
                    if output_file.exists():
                        output_file.unlink()
                    return False
            else:
                logger.error(f"Ошибка ffmpeg: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Таймаут при конвертации {input_file}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при конвертации {input_file}: {e}")
            return False

    def process_file(self, file_path: Path, delete_original: bool = False) -> Dict:
        """Обработка одного видеофайла"""
        result = {
            'file': str(file_path),
            'status': 'unknown',
            'message': '',
            'timestamp': datetime.now().isoformat()
        }

        try:
            logger.info(f"Анализируем: {file_path.name}")

            # Получаем информацию о дорожках
            tracks = self.get_audio_tracks(file_path)
            if not tracks:
                result['status'] = 'no_audio'
                result['message'] = 'Аудио дорожки не найдены'
                logger.warning(f"❌ Нет аудио дорожек: {file_path.name}")
                return result

            # Ищем английские дорожки
            eng_stereo, eng_surround = self.find_english_tracks(tracks)

            if eng_stereo:
                result['status'] = 'has_stereo'
                result['message'] = f'Уже есть стерео дорожка: {eng_stereo}'
                logger.info(f"✅ Уже есть стерео: {file_path.name}")
                return result

            if eng_surround:
                # Конвертируем 5.1 в стерео
                output_file = file_path.with_suffix('.converted' + file_path.suffix)

                if self.convert_audio(file_path, output_file, eng_surround, not delete_original):
                    result['status'] = 'converted'
                    result['message'] = f'Конвертирована дорожка: {eng_surround}'

                    # Очистка временного файла если нужно
                    if not delete_original and output_file.exists():
                        # Оставляем конвертированный файл рядом с оригиналом
                        new_name = file_path.with_suffix('.stereo' + file_path.suffix)
                        shutil.move(str(output_file), str(new_name))
                        result['converted_file'] = str(new_name)
                else:
                    result['status'] = 'conversion_failed'
                    result['message'] = 'Ошибка при конвертации'
            else:
                result['status'] = 'no_english'
                result['message'] = 'Английские дорожки не найдены'
                logger.warning(f"⚠️ Нет английских дорожек: {file_path.name}")

                # Логируем найденные дорожки для отладки
                for track in tracks:
                    logger.debug(f"  {track}")

        except Exception as e:
            result['status'] = 'error'
            result['message'] = str(e)
            logger.error(f"Ошибка при обработке {file_path}: {e}")

        return result

    def scan_directory(self, directory: Path, max_depth: int = 2,
                       current_depth: int = 0) -> List[Path]:
        """Рекурсивное сканирование директории"""
        video_files = []

        if current_depth > max_depth:
            return video_files

        try:
            for item in directory.iterdir():
                if item.is_dir():
                    # Рекурсивно сканируем поддиректории
                    video_files.extend(
                        self.scan_directory(item, max_depth, current_depth + 1)
                    )
                elif item.is_file():
                    # Проверяем расширение файла
                    if item.suffix.lower() in self.config['video_extensions']:
                        video_files.append(item)

        except PermissionError:
            logger.warning(f"Нет доступа к директории: {directory}")

        return video_files

    def process_directory(self, directory: Path, delete_original: bool = False):
        """Обработка всех видеофайлов в директории"""
        logger.info(f"Начинаем сканирование: {directory}")
        logger.info(f"Режим: {'Удаление оригиналов' if delete_original else 'Сохранение оригиналов'}")

        # Загружаем состояние
        state = self.load_state(directory)

        # Сканируем директорию
        video_files = self.scan_directory(directory, self.config['max_depth'])
        logger.info(f"Найдено видеофайлов: {len(video_files)}")

        # Статистика
        stats = {
            'total': len(video_files),
            'processed': 0,
            'has_stereo': 0,
            'converted': 0,
            'no_english': 0,
            'errors': 0
        }

        # Обрабатываем каждый файл
        for i, file_path in enumerate(video_files, 1):
            file_key = str(file_path)

            # Проверяем, обработан ли файл ранее
            if file_key in state and state[file_key].get('status') == 'has_stereo':
                logger.info(f"[{i}/{stats['total']}] Пропускаем (уже обработан): {file_path.name}")
                stats['has_stereo'] += 1
                continue

            logger.info(f"[{i}/{stats['total']}] Обрабатываем: {file_path.name}")

            # Обрабатываем файл
            result = self.process_file(file_path, delete_original)

            # Обновляем состояние
            state[file_key] = result

            # Обновляем статистику
            stats['processed'] += 1
            if result['status'] == 'has_stereo':
                stats['has_stereo'] += 1
            elif result['status'] == 'converted':
                stats['converted'] += 1
            elif result['status'] == 'no_english':
                stats['no_english'] += 1
            elif result['status'] in ['error', 'conversion_failed']:
                stats['errors'] += 1

            # Сохраняем состояние после каждого файла
            self.save_state(directory, state)

            # Небольшая пауза между файлами
            time.sleep(0.5)

        # Выводим итоговую статистику
        logger.info("=" * 60)
        logger.info("ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(f"Всего файлов: {stats['total']}")
        logger.info(f"Обработано: {stats['processed']}")
        logger.info(f"Уже имеют стерео: {stats['has_stereo']}")
        logger.info(f"Конвертировано: {stats['converted']}")
        logger.info(f"Без английских дорожек: {stats['no_english']}")
        logger.info(f"Ошибок: {stats['errors']}")
        logger.info("=" * 60)

        # Создаем отчет о файлах без английских дорожек
        if stats['no_english'] > 0:
            no_english_files = [k for k, v in state.items()
                                if v.get('status') == 'no_english']

            report_file = directory / 'no_english_tracks_report.txt'
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("Файлы без английских аудио дорожек:\n")
                f.write("=" * 60 + "\n")
                for file in no_english_files:
                    f.write(f"{file}\n")

            logger.info(f"Отчет сохранен в: {report_file}")


def check_dependencies():
    """Проверка наличия необходимых программ"""
    dependencies = ['ffmpeg', 'ffprobe']
    missing = []

    for dep in dependencies:
        try:
            subprocess.run([dep, '-version'], capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            missing.append(dep)

    if missing:
        logger.error(f"Не найдены необходимые программы: {', '.join(missing)}")
        logger.error("Установите ffmpeg: https://ffmpeg.org/download.html")
        return False

    return True


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='Автоматическая конвертация 5.1 аудио в стерео для Plex'
    )
    parser.add_argument(
        'directory',
        type=str,
        help='Путь к директории с видеофайлами (например: E:\\Download\\Movie)'
    )
    parser.add_argument(
        '--delete-original',
        action='store_true',
        help='Удалить оригинальные файлы после конвертации'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Тестовый запуск без реальной конвертации'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Путь к файлу конфигурации JSON'
    )

    args = parser.parse_args()

    # Проверяем зависимости
    if not check_dependencies():
        sys.exit(1)

    # Загружаем конфигурацию из файла если указан
    config = CONFIG.copy()
    if args.config and Path(args.config).exists():
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                custom_config = json.load(f)
                config.update(custom_config)
                logger.info(f"Загружена конфигурация из: {args.config}")
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            sys.exit(1)

    # Проверяем существование директории
    directory = Path(args.directory)
    if not directory.exists():
        logger.error(f"Директория не существует: {directory}")
        sys.exit(1)

    if not directory.is_dir():
        logger.error(f"Это не директория: {directory}")
        sys.exit(1)

    # Режим тестового запуска
    if args.dry_run:
        logger.info("РЕЖИМ ТЕСТОВОГО ЗАПУСКА - файлы не будут изменены")
        config['ffmpeg_path'] = 'echo'  # Заменяем ffmpeg на echo для теста

    # Создаем процессор и запускаем обработку
    processor = VideoFileProcessor(config)
    processor.process_directory(directory, args.delete_original)

    logger.info("Обработка завершена!")


if __name__ == "__main__":
    main()