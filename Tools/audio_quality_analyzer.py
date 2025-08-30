#!/usr/bin/env python3
"""
Audio Quality Analyzer - Объективный анализ качества аудио после конвертации
Проверяет соотношение диалогов/музыки, динамический диапазон, LUFS и другие параметры

Автор: Assistant
Версия: 1.0
"""

import os
import sys
import json
import subprocess
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging
import argparse

# Дополнительные библиотеки для анализа
try:
    import librosa
    import librosa.display
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    print("Внимание: librosa не установлена. Установите: pip install librosa")

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False
    print("Внимание: soundfile не установлена. Установите: pip install soundfile")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audio_quality_analysis.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def resolve_path(path_str: str) -> Path:
    """Resolves a path string to a Path object, handling both relative and absolute paths"""
    path = Path(path_str)
    
    # If it's already absolute and exists, return it
    if path.is_absolute() and path.exists():
        return path
    
    # Try as relative path
    if path.exists():
        return path.resolve()
    
    # Try as absolute path if relative failed
    if not path.is_absolute():
        abs_path = Path(path_str)
        if abs_path.exists():
            return abs_path
    
    # Return original path even if it doesn't exist (let caller handle error)
    return path

class AudioQualityAnalyzer:
    """Класс для анализа качества аудио"""
    
    # Целевые параметры для качественного стерео звука для ТВ
    QUALITY_TARGETS = {
        'lufs_integrated': {
            'min': -24,  # Минимальная интегральная громкость
            'max': -16,  # Максимальная интегральная громкость
            'ideal': -23  # Рекомендация EBU R128 для вещания
        },
        'lufs_range': {
            'min': 4,    # Минимальный динамический диапазон
            'max': 15,   # Максимальный динамический диапазон
            'ideal': 7   # Оптимально для ТВ контента
        },
        'true_peak': {
            'max': -1.0  # Максимальный true peak (dBTP)
        },
        'dialog_ratio': {
            'min': 0.35,  # Минимальное соотношение диалогов к общему звуку
            'ideal': 0.50  # Идеальное соотношение для фильмов/сериалов
        },
        'center_presence': {
            'min': 0.30,  # Минимальное присутствие центрального канала в стерео
            'ideal': 0.45  # Идеальное присутствие (после downmix)
        },
        'frequency_balance': {
            'bass_ratio': (0.15, 0.30),    # Соотношение низких частот (< 250 Hz)
            'mid_ratio': (0.40, 0.60),     # Соотношение средних частот (250-4000 Hz)
            'treble_ratio': (0.15, 0.30)   # Соотношение высоких частот (> 4000 Hz)
        }
    }
    
    def __init__(self, ffmpeg_path: str = 'ffmpeg', ffprobe_path: str = 'ffprobe'):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.analysis_results = {}
        
    def analyze_lufs(self, file_path: Path) -> Dict:
        """Анализ громкости по стандарту EBU R128 (LUFS)"""
        logger.info(f"Анализируем LUFS: {file_path.name}")
        
        try:
            # Используем ffmpeg с фильтром ebur128
            cmd = [
                self.ffmpeg_path,
                '-i', str(file_path),
                '-af', 'ebur128=peak=true:framelog=quiet',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            output = result.stderr
            
            # Парсим результаты
            lufs_data = {
                'integrated': None,
                'range': None,
                'true_peak': None,
                'short_term_max': None,
                'momentary_max': None
            }
            
            for line in output.split('\n'):
                if 'I:' in line and 'LUFS' in line:
                    # Integrated LUFS
                    try:
                        value = line.split('I:')[1].split('LUFS')[0].strip()
                        lufs_data['integrated'] = float(value)
                    except:
                        pass
                elif 'LRA:' in line and 'LU' in line:
                    # Loudness Range
                    try:
                        value = line.split('LRA:')[1].split('LU')[0].strip()
                        lufs_data['range'] = float(value)
                    except:
                        pass
                elif 'Peak:' in line and 'dBFS' in line:
                    # True Peak
                    try:
                        value = line.split('Peak:')[1].split('dBFS')[0].strip()
                        lufs_data['true_peak'] = float(value)
                    except:
                        pass
            
            return lufs_data
            
        except Exception as e:
            logger.error(f"Ошибка анализа LUFS: {e}")
            return {}
    
    def analyze_frequency_spectrum(self, file_path: Path, duration_seconds: int = 60) -> Dict:
        """Анализ частотного спектра"""
        if not LIBROSA_AVAILABLE:
            logger.warning("librosa не установлена, пропускаем спектральный анализ")
            return {}
        
        logger.info(f"Анализируем частотный спектр: {file_path.name}")
        
        try:
            # Извлекаем аудио в WAV для анализа
            temp_wav = Path('temp_analysis.wav')
            cmd = [
                self.ffmpeg_path,
                '-i', str(file_path),
                '-t', str(duration_seconds),  # Анализируем первые N секунд
                '-ac', '2',  # Стерео
                '-ar', '48000',  # Sample rate
                '-y',
                str(temp_wav)
            ]
            
            subprocess.run(cmd, capture_output=True, timeout=60)
            
            if not temp_wav.exists():
                return {}
            
            # Загружаем аудио
            y, sr = librosa.load(temp_wav, sr=48000, mono=False)
            
            # Если стерео, берем среднее
            if y.ndim > 1:
                y = np.mean(y, axis=0)
            
            # Вычисляем спектрограмму
            D = np.abs(librosa.stft(y))
            freqs = librosa.fft_frequencies(sr=sr)
            
            # Разделяем на частотные диапазоны
            bass_mask = freqs < 250
            mid_mask = (freqs >= 250) & (freqs < 4000)
            treble_mask = freqs >= 4000
            
            # Вычисляем энергию в каждом диапазоне
            total_energy = np.sum(D)
            bass_energy = np.sum(D[bass_mask, :])
            mid_energy = np.sum(D[mid_mask, :])
            treble_energy = np.sum(D[treble_mask, :])
            
            frequency_data = {
                'bass_ratio': bass_energy / total_energy,
                'mid_ratio': mid_energy / total_energy,
                'treble_ratio': treble_energy / total_energy,
                'spectral_centroid': float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))),
                'spectral_rolloff': float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
            }
            
            # Удаляем временный файл
            temp_wav.unlink()
            
            return frequency_data
            
        except Exception as e:
            logger.error(f"Ошибка анализа спектра: {e}")
            return {}
    
    def analyze_dialog_presence(self, file_path: Path, sample_points: int = 5) -> Dict:
        """Анализ присутствия диалогов (частоты человеческого голоса)"""
        if not LIBROSA_AVAILABLE:
            return {}
        
        logger.info(f"Анализируем присутствие диалогов: {file_path.name}")
        
        try:
            # Извлекаем несколько фрагментов для анализа
            dialog_scores = []
            
            # Получаем длительность файла
            duration = self.get_duration(file_path)
            if not duration:
                return {}
            
            # Анализируем несколько точек
            for i in range(sample_points):
                start_time = (duration / (sample_points + 1)) * (i + 1)
                
                # Извлекаем 10-секундный фрагмент
                temp_wav = Path(f'temp_dialog_{i}.wav')
                cmd = [
                    self.ffmpeg_path,
                    '-ss', str(int(start_time)),
                    '-i', str(file_path),
                    '-t', '10',
                    '-ac', '2',
                    '-ar', '16000',  # Понижаем частоту для анализа голоса
                    '-y',
                    str(temp_wav)
                ]
                
                subprocess.run(cmd, capture_output=True, timeout=30)
                
                if temp_wav.exists():
                    # Загружаем аудио
                    y, sr = librosa.load(temp_wav, sr=16000, mono=True)
                    
                    # Анализируем частоты голоса (85-255 Hz для мужского, 165-255 Hz для женского)
                    D = np.abs(librosa.stft(y))
                    freqs = librosa.fft_frequencies(sr=sr)
                    
                    voice_mask = (freqs >= 85) & (freqs <= 3000)  # Расширенный диапазон голоса
                    voice_energy = np.sum(D[voice_mask, :])
                    total_energy = np.sum(D)
                    
                    if total_energy > 0:
                        dialog_score = voice_energy / total_energy
                        dialog_scores.append(dialog_score)
                    
                    temp_wav.unlink()
            
            if dialog_scores:
                return {
                    'dialog_ratio': float(np.mean(dialog_scores)),
                    'dialog_consistency': float(np.std(dialog_scores)),
                    'samples_analyzed': len(dialog_scores)
                }
            
        except Exception as e:
            logger.error(f"Ошибка анализа диалогов: {e}")
        
        return {}
    
    def analyze_stereo_balance(self, file_path: Path) -> Dict:
        """Анализ баланса стерео каналов"""
        logger.info(f"Анализируем стерео баланс: {file_path.name}")
        
        try:
            # Анализируем баланс каналов через ffmpeg
            cmd = [
                self.ffmpeg_path,
                '-i', str(file_path),
                '-af', 'astats=metadata=1:reset=1',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            output = result.stderr
            
            balance_data = {
                'left_rms': None,
                'right_rms': None,
                'balance_ratio': None,
                'correlation': None
            }
            
            # Парсим RMS уровни
            for line in output.split('\n'):
                if 'RMS level' in line:
                    if 'Ch1' in line or 'Channel: 1' in line:
                        try:
                            value = float(line.split(':')[-1].strip().split()[0])
                            balance_data['left_rms'] = value
                        except:
                            pass
                    elif 'Ch2' in line or 'Channel: 2' in line:
                        try:
                            value = float(line.split(':')[-1].strip().split()[0])
                            balance_data['right_rms'] = value
                        except:
                            pass
            
            # Вычисляем баланс
            if balance_data['left_rms'] and balance_data['right_rms']:
                left = abs(balance_data['left_rms'])
                right = abs(balance_data['right_rms'])
                if left + right > 0:
                    balance_data['balance_ratio'] = left / (left + right)
            
            return balance_data
            
        except Exception as e:
            logger.error(f"Ошибка анализа стерео баланса: {e}")
            return {}
    
    def compare_with_original(self, original_path: Path, converted_path: Path) -> Dict:
        """Сравнение конвертированного файла с оригиналом"""
        logger.info("Сравниваем с оригиналом...")
        
        comparison = {
            'original': {},
            'converted': {},
            'improvements': {},
            'warnings': []
        }
        
        # Анализируем оригинал
        logger.info("Анализируем оригинальный файл...")
        orig_lufs = self.analyze_lufs(original_path)
        orig_spectrum = self.analyze_frequency_spectrum(original_path, duration_seconds=30)
        
        comparison['original'] = {
            'lufs': orig_lufs,
            'spectrum': orig_spectrum
        }
        
        # Анализируем конвертированный
        logger.info("Анализируем конвертированный файл...")
        conv_lufs = self.analyze_lufs(converted_path)
        conv_spectrum = self.analyze_frequency_spectrum(converted_path, duration_seconds=30)
        conv_dialog = self.analyze_dialog_presence(converted_path, sample_points=3)
        
        comparison['converted'] = {
            'lufs': conv_lufs,
            'spectrum': conv_spectrum,
            'dialog': conv_dialog
        }
        
        # Оцениваем улучшения
        if orig_lufs.get('integrated') and conv_lufs.get('integrated'):
            lufs_diff = conv_lufs['integrated'] - orig_lufs['integrated']
            comparison['improvements']['loudness_boost'] = lufs_diff
            
            if lufs_diff > 0:
                logger.info(f"✅ Громкость увеличена на {lufs_diff:.1f} LUFS")
            else:
                logger.warning(f"⚠️ Громкость уменьшена на {abs(lufs_diff):.1f} LUFS")
        
        if orig_spectrum.get('mid_ratio') and conv_spectrum.get('mid_ratio'):
            mid_boost = conv_spectrum['mid_ratio'] - orig_spectrum['mid_ratio']
            comparison['improvements']['midrange_boost'] = mid_boost
            
            if mid_boost > 0.05:
                logger.info(f"✅ Средние частоты (диалоги) усилены на {mid_boost*100:.1f}%")
        
        return comparison
    
    def get_duration(self, file_path: Path) -> Optional[float]:
        """Получение длительности файла"""
        try:
            cmd = [
                self.ffprobe_path,
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'json',
                str(file_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)
            return float(data['format']['duration'])
        except:
            return None
    
    def evaluate_quality(self, analysis_data: Dict) -> Dict:
        """Оценка качества на основе анализа"""
        evaluation = {
            'overall_score': 0,
            'passed_checks': [],
            'failed_checks': [],
            'warnings': [],
            'recommendations': []
        }
        
        total_checks = 0
        passed_checks = 0
        
        # Проверка LUFS
        if 'lufs' in analysis_data:
            lufs = analysis_data['lufs']
            
            # Интегральная громкость
            if lufs.get('integrated'):
                total_checks += 1
                targets = self.QUALITY_TARGETS['lufs_integrated']
                if targets['min'] <= lufs['integrated'] <= targets['max']:
                    passed_checks += 1
                    evaluation['passed_checks'].append(
                        f"✅ Громкость в норме: {lufs['integrated']:.1f} LUFS"
                    )
                else:
                    evaluation['failed_checks'].append(
                        f"❌ Громкость вне диапазона: {lufs['integrated']:.1f} LUFS (норма: {targets['min']} до {targets['max']})"
                    )
                    if lufs['integrated'] < targets['min']:
                        evaluation['recommendations'].append(
                            "Увеличьте громкость или используйте нормализацию"
                        )
            
            # Динамический диапазон
            if lufs.get('range'):
                total_checks += 1
                targets = self.QUALITY_TARGETS['lufs_range']
                if targets['min'] <= lufs['range'] <= targets['max']:
                    passed_checks += 1
                    evaluation['passed_checks'].append(
                        f"✅ Динамический диапазон в норме: {lufs['range']:.1f} LU"
                    )
                else:
                    evaluation['failed_checks'].append(
                        f"❌ Динамический диапазон: {lufs['range']:.1f} LU (норма: {targets['min']} до {targets['max']})"
                    )
                    if lufs['range'] < targets['min']:
                        evaluation['warnings'].append(
                            "⚠️ Слишком сжатый звук, возможна потеря динамики"
                        )
            
            # True Peak
            if lufs.get('true_peak'):
                total_checks += 1
                if lufs['true_peak'] <= self.QUALITY_TARGETS['true_peak']['max']:
                    passed_checks += 1
                    evaluation['passed_checks'].append(
                        f"✅ True Peak в норме: {lufs['true_peak']:.1f} dBTP"
                    )
                else:
                    evaluation['failed_checks'].append(
                        f"❌ True Peak превышен: {lufs['true_peak']:.1f} dBTP (макс: {self.QUALITY_TARGETS['true_peak']['max']})"
                    )
                    evaluation['recommendations'].append(
                        "Используйте лимитер для предотвращения клиппинга"
                    )
        
        # Проверка частотного баланса
        if 'spectrum' in analysis_data:
            spectrum = analysis_data['spectrum']
            
            if spectrum.get('mid_ratio'):
                total_checks += 1
                targets = self.QUALITY_TARGETS['frequency_balance']['mid_ratio']
                if targets[0] <= spectrum['mid_ratio'] <= targets[1]:
                    passed_checks += 1
                    evaluation['passed_checks'].append(
                        f"✅ Средние частоты сбалансированы: {spectrum['mid_ratio']*100:.1f}%"
                    )
                else:
                    evaluation['warnings'].append(
                        f"⚠️ Дисбаланс средних частот: {spectrum['mid_ratio']*100:.1f}%"
                    )
        
        # Проверка диалогов
        if 'dialog' in analysis_data:
            dialog = analysis_data['dialog']
            
            if dialog.get('dialog_ratio'):
                total_checks += 1
                targets = self.QUALITY_TARGETS['dialog_ratio']
                if dialog['dialog_ratio'] >= targets['min']:
                    passed_checks += 1
                    evaluation['passed_checks'].append(
                        f"✅ Диалоги присутствуют: {dialog['dialog_ratio']*100:.1f}%"
                    )
                else:
                    evaluation['failed_checks'].append(
                        f"❌ Слабое присутствие диалогов: {dialog['dialog_ratio']*100:.1f}%"
                    )
                    evaluation['recommendations'].append(
                        "Проверьте формулу downmix, возможно нужно усилить центральный канал"
                    )
        
        # Вычисляем общий балл
        if total_checks > 0:
            evaluation['overall_score'] = (passed_checks / total_checks) * 100
        
        # Добавляем итоговую оценку
        if evaluation['overall_score'] >= 80:
            evaluation['verdict'] = "🎉 ОТЛИЧНО - звук соответствует всем критериям"
        elif evaluation['overall_score'] >= 60:
            evaluation['verdict'] = "👍 ХОРОШО - звук приемлемый, есть небольшие замечания"
        elif evaluation['overall_score'] >= 40:
            evaluation['verdict'] = "⚠️ УДОВЛЕТВОРИТЕЛЬНО - требуется доработка"
        else:
            evaluation['verdict'] = "❌ ПЛОХО - требуется пересмотр параметров конвертации"
        
        return evaluation
    
    def generate_report(self, file_path: Path, save_plots: bool = True) -> Dict:
        """Генерация полного отчета о качестве"""
        logger.info(f"Генерируем полный отчет для: {file_path.name}")
        
        report = {
            'file': str(file_path),
            'timestamp': datetime.now().isoformat(),
            'analysis': {},
            'evaluation': {},
            'plots_generated': []
        }
        
        # Выполняем все анализы
        report['analysis']['lufs'] = self.analyze_lufs(file_path)
        report['analysis']['spectrum'] = self.analyze_frequency_spectrum(file_path)
        report['analysis']['dialog'] = self.analyze_dialog_presence(file_path)
        report['analysis']['stereo'] = self.analyze_stereo_balance(file_path)
        
        # Оцениваем качество
        report['evaluation'] = self.evaluate_quality(report['analysis'])
        
        # Генерируем графики
        if save_plots and LIBROSA_AVAILABLE:
            plot_files = self.generate_plots(file_path, report['analysis'])
            report['plots_generated'] = plot_files
        
        # Сохраняем отчет в JSON
        report_file = file_path.with_suffix('.quality_report.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Отчет сохранен: {report_file}")
        
        return report
    
    def generate_plots(self, file_path: Path, analysis_data: Dict) -> List[str]:
        """Генерация графиков для визуализации"""
        plots = []
        
        try:
            # График частотного спектра
            if 'spectrum' in analysis_data and analysis_data['spectrum']:
                fig, axes = plt.subplots(2, 2, figsize=(12, 8))
                fig.suptitle(f'Анализ качества: {file_path.name}', fontsize=14)
                
                # Частотный баланс
                ax = axes[0, 0]
                frequencies = ['Низкие\n(<250Hz)', 'Средние\n(250-4kHz)', 'Высокие\n(>4kHz)']
                values = [
                    analysis_data['spectrum'].get('bass_ratio', 0) * 100,
                    analysis_data['spectrum'].get('mid_ratio', 0) * 100,
                    analysis_data['spectrum'].get('treble_ratio', 0) * 100
                ]
                colors = ['#FF6B6B', '#4ECDC4', '#45B7D1']
                bars = ax.bar(frequencies, values, color=colors)
                ax.set_ylabel('Процент энергии (%)')
                ax.set_title('Частотный баланс')
                ax.set_ylim(0, 100)
                
                # Добавляем целевые диапазоны
                ax.axhspan(15, 30, alpha=0.2, color='gray', label='Целевой диапазон')
                ax.axhspan(40, 60, alpha=0.2, color='gray')
                
                # LUFS метрики
                if 'lufs' in analysis_data and analysis_data['lufs']:
                    ax = axes[0, 1]
                    lufs_data = analysis_data['lufs']
                    
                    metrics = []
                    values = []
                    colors_lufs = []
                    
                    if lufs_data.get('integrated'):
                        metrics.append('Integrated\nLUFS')
                        values.append(lufs_data['integrated'])
                        # Цвет в зависимости от соответствия норме
                        if -24 <= lufs_data['integrated'] <= -16:
                            colors_lufs.append('#4ECDC4')
                        else:
                            colors_lufs.append('#FF6B6B')
                    
                    if lufs_data.get('range'):
                        metrics.append('Dynamic\nRange (LU)')
                        values.append(lufs_data['range'])
                        if 4 <= lufs_data['range'] <= 15:
                            colors_lufs.append('#4ECDC4')
                        else:
                            colors_lufs.append('#FF6B6B')
                    
                    if metrics:
                        bars = ax.bar(metrics, values, color=colors_lufs)
                        ax.set_ylabel('Значение')
                        ax.set_title('Громкость (EBU R128)')
                        ax.axhline(y=-23, color='green', linestyle='--', alpha=0.5, label='Целевая громкость')
                        ax.legend()
                
                # Присутствие диалогов
                if 'dialog' in analysis_data and analysis_data['dialog']:
                    ax = axes[1, 0]
                    dialog_ratio = analysis_data['dialog'].get('dialog_ratio', 0) * 100
                    
                    # Круговая диаграмма
                    sizes = [dialog_ratio, 100 - dialog_ratio]
                    labels = ['Диалоги', 'Остальное']
                    colors_pie = ['#4ECDC4', '#E8E8E8']
                    explode = (0.1, 0)
                    
                    ax.pie(sizes, explode=explode, labels=labels, colors=colors_pie,
                          autopct='%1.1f%%', shadow=True, startangle=90)
                    ax.set_title('Соотношение диалогов')
                
                # Оценка качества
                if 'evaluation' in analysis_data:
                    ax = axes[1, 1]
                    ax.axis('off')
                    
                    eval_data = self.evaluate_quality(analysis_data)
                    score = eval_data.get('overall_score', 0)
                    
                    # Цветовая индикация
                    if score >= 80:
                        color = '#4ECDC4'
                    elif score >= 60:
                        color = '#FFD93D'
                    elif score >= 40:
                        color = '#FFA500'
                    else:
                        color = '#FF6B6B'
                    
                    # Большой круг с оценкой
                    circle = plt.Circle((0.5, 0.5), 0.4, color=color, alpha=0.7)
                    ax.add_patch(circle)
                    ax.text(0.5, 0.5, f'{score:.0f}%', fontsize=36, fontweight='bold',
                           ha='center', va='center')
                    ax.text(0.5, 0.15, 'Оценка качества', fontsize=12, ha='center')
                    ax.set_xlim(0, 1)
                    ax.set_ylim(0, 1)
                
                plt.tight_layout()
                
                # Сохраняем график
                plot_file = file_path.with_suffix('.quality_analysis.png')
                plt.savefig(plot_file, dpi=150, bbox_inches='tight')
                plt.close()
                
                plots.append(str(plot_file))
                logger.info(f"График сохранен: {plot_file}")
                
        except Exception as e:
            logger.error(f"Ошибка генерации графиков: {e}")
        
        return plots
    
    def batch_analyze(self, directory: Path, patterns: List[str] = None) -> Dict:
        """Пакетный анализ файлов"""
        if patterns is None:
            patterns = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.m4v", "*.flv", "*.webm", "*.wav", "*.mp3", "*.flac", "*.aac", "*.m4a"]
        
        results = {}
        files = []
        
        # Собираем все файлы по всем паттернам
        for pattern in patterns:
            files.extend(directory.glob(pattern))
        
        logger.info(f"Найдено файлов для анализа: {len(files)}")
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"[{i}/{len(files)}] Анализируем: {file_path.name}")
            report = self.generate_report(file_path, save_plots=True)
            results[str(file_path)] = report
        
        # Сохраняем сводный отчет
        summary_file = directory / 'quality_analysis_summary.json'
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Сводный отчет сохранен: {summary_file}")
        
        return results

def print_report(report: Dict):
    """Красивый вывод отчета в консоль"""
    print("\n" + "="*60)
    print("📊 ОТЧЕТ О КАЧЕСТВЕ АУДИО")
    print("="*60)
    
    if 'analysis' in report:
        analysis = report['analysis']
        
        # LUFS
        if 'lufs' in analysis and analysis['lufs']:
            print("\n🔊 Громкость (LUFS):")
            lufs = analysis['lufs']
            if lufs.get('integrated'):
                print(f"  • Интегральная: {lufs['integrated']:.1f} LUFS")
            if lufs.get('range'):
                print(f"  • Динамический диапазон: {lufs['range']:.1f} LU")
            if lufs.get('true_peak'):
                print(f"  • True Peak: {lufs['true_peak']:.1f} dBTP")
        
        # Частотный баланс
        if 'spectrum' in analysis and analysis['spectrum']:
            print("\n🎵 Частотный баланс:")
            spectrum = analysis['spectrum']
            if spectrum.get('bass_ratio'):
                print(f"  • Низкие частоты: {spectrum['bass_ratio']*100:.1f}%")
            if spectrum.get('mid_ratio'):
                print(f"  • Средние частоты: {spectrum['mid_ratio']*100:.1f}%")
            if spectrum.get('treble_ratio'):
                print(f"  • Высокие частоты: {spectrum['treble_ratio']*100:.1f}%")
        
        # Диалоги
        if 'dialog' in analysis and analysis['dialog']:
            print("\n💬 Анализ диалогов:")
            dialog = analysis['dialog']
            if dialog.get('dialog_ratio'):
                print(f"  • Присутствие диалогов: {dialog['dialog_ratio']*100:.1f}%")
            if dialog.get('dialog_consistency'):
                print(f"  • Консистентность: {dialog['dialog_consistency']*100:.1f}%")
    
    # Оценка
    if 'evaluation' in report:
        eval_data = report['evaluation']
        
        print("\n" + "="*60)
        print("📈 ОЦЕНКА КАЧЕСТВА")
        print("="*60)
        
        print(f"\n🎯 Общий балл: {eval_data.get('overall_score', 0):.0f}/100")
        print(f"\n{eval_data.get('verdict', 'Нет оценки')}")
        
        if eval_data.get('passed_checks'):
            print("\n✅ Пройденные проверки:")
            for check in eval_data['passed_checks']:
                print(f"  {check}")
        
        if eval_data.get('failed_checks'):
            print("\n❌ Проваленные проверки:")
            for check in eval_data['failed_checks']:
                print(f"  {check}")
        
        if eval_data.get('warnings'):
            print("\n⚠️ Предупреждения:")
            for warning in eval_data['warnings']:
                print(f"  {warning}")
        
        if eval_data.get('recommendations'):
            print("\n💡 Рекомендации:")
            for rec in eval_data['recommendations']:
                print(f"  • {rec}")
    
    print("\n" + "="*60)

def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='Объективный анализ качества аудио после конвертации'
    )
    parser.add_argument(
        'file',
        type=str,
        help='Путь к видео/аудио файлу для анализа'
    )
    parser.add_argument(
        '--compare',
        type=str,
        help='Путь к оригинальному файлу для сравнения'
    )
    parser.add_argument(
        '--batch',
        action='store_true',
        help='Пакетный анализ всех файлов в директории'
    )
    parser.add_argument(
        '--no-plots',
        action='store_true',
        help='Не генерировать графики'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Вывести результат в JSON формате'
    )
    
    args = parser.parse_args()
    
    # Проверяем наличие ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    except:
        print("Ошибка: ffmpeg не найден. Установите ffmpeg для продолжения.")
        sys.exit(1)
    
    # Создаем анализатор
    analyzer = AudioQualityAnalyzer()
    
    if args.batch:
        # Пакетный анализ
        directory = resolve_path(args.file)
        if not directory.is_dir():
            print(f"Ошибка: {directory} не является директорией")
            sys.exit(1)
        
        results = analyzer.batch_analyze(directory)
        
        if not args.json:
            print(f"\nПроанализировано файлов: {len(results)}")
            for file, report in results.items():
                print(f"\n📁 {Path(file).name}")
                if 'evaluation' in report:
                    score = report['evaluation'].get('overall_score', 0)
                    verdict = report['evaluation'].get('verdict', '')
                    print(f"   Оценка: {score:.0f}/100 - {verdict}")
    else:
        # Анализ одного файла
        file_path = resolve_path(args.file)
        if not file_path.exists():
            print(f"Ошибка: файл {file_path} не найден")
            sys.exit(1)
        
        if args.compare:
            # Сравнение с оригиналом
            original_path = resolve_path(args.compare)
            if not original_path.exists():
                print(f"Ошибка: оригинальный файл {original_path} не найден")
                sys.exit(1)
            
            comparison = analyzer.compare_with_original(original_path, file_path)
            
            if args.json:
                print(json.dumps(comparison, indent=2, ensure_ascii=False))
            else:
                print("\n📊 СРАВНЕНИЕ С ОРИГИНАЛОМ")
                print("="*60)
                
                if 'improvements' in comparison:
                    imp = comparison['improvements']
                    if 'loudness_boost' in imp:
                        boost = imp['loudness_boost']
                        if boost > 0:
                            print(f"✅ Громкость увеличена на {boost:.1f} LUFS")
                        else:
                            print(f"⚠️ Громкость уменьшена на {abs(boost):.1f} LUFS")
                    
                    if 'midrange_boost' in imp:
                        mid_boost = imp['midrange_boost']
                        if mid_boost > 0:
                            print(f"✅ Средние частоты усилены на {mid_boost*100:.1f}%")
        else:
            # Простой анализ
            report = analyzer.generate_report(file_path, save_plots=not args.no_plots)
            
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print_report(report)
    
    print("\nAnalysis completed!")

if __name__ == "__main__":
    main()
    