#!/usr/bin/env python3
"""
Download Monitor Test Tool

Тестирует функциональность мониторинга загрузок файлов.
Создает тестовые файлы с различными статусами для проверки системы.
"""

import os
import sys
import time
import asyncio
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.download_monitor import DownloadMonitor, DownloadStatus
from core.logger import logger


class DownloadMonitorTester:
    """Класс для тестирования мониторинга загрузок"""
    
    def __init__(self, test_dir: str = "/temp/download_test"):
        self.test_dir = Path(test_dir)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.monitor = DownloadMonitor(stability_threshold=5.0)  # 5 секунд для тестов
        self.monitor.add_callback(self._on_status_change)
        
    def _on_status_change(self, file_info):
        """Обработчик изменения статуса файла"""
        print(f"📊 Статус изменен: {file_info.file_path.name} -> {file_info.status.value}")
        print(f"   Метод обнаружения: {file_info.detection_method}")
        print(f"   Размер: {file_info.size / (1024*1024):.1f} МБ")
        print(f"   Стабильность: {file_info.stable_duration:.1f}с")
        print()
        
    def create_test_files(self):
        """Создание тестовых файлов"""
        print("🔧 Создание тестовых файлов...")
        
        # 1. Файл с расширением .part (загружается)
        part_file = self.test_dir / "movie1.mkv.part"
        with open(part_file, 'wb') as f:
            f.write(b"0" * (50 * 1024 * 1024))  # 50 МБ
        print(f"✅ Создан: {part_file.name}")
        
        # 2. Файл с расширением .!ut (uTorrent)
        ut_file = self.test_dir / "movie2.mp4.!ut"
        with open(ut_file, 'wb') as f:
            f.write(b"0" * (100 * 1024 * 1024))  # 100 МБ
        print(f"✅ Создан: {ut_file.name}")
        
        # 3. Обычный файл (будет считаться завершенным после стабилизации)
        normal_file = self.test_dir / "movie3.mkv"
        with open(normal_file, 'wb') as f:
            f.write(b"0" * (200 * 1024 * 1024))  # 200 МБ
        print(f"✅ Создан: {normal_file.name}")
        
        # 4. Файл, который будет "расти" (имитация загрузки)
        growing_file = self.test_dir / "movie4.mp4"
        with open(growing_file, 'wb') as f:
            f.write(b"0" * (10 * 1024 * 1024))  # Начинаем с 10 МБ
        print(f"✅ Создан: {growing_file.name}")
        
        return [part_file, ut_file, normal_file, growing_file]
        
    def simulate_download_completion(self, files):
        """Имитация завершения загрузки"""
        print("\n🎬 Начинаем имитацию процесса загрузки...")
        
        part_file, ut_file, normal_file, growing_file = files
        
        # Добавляем файлы в мониторинг
        for file_path in files:
            self.monitor.add_file(file_path, is_torrent_file=True)
            
        # Запускаем мониторинг
        self.monitor.start_monitoring(check_interval=2.0)
        
        return asyncio.create_task(self._simulate_async(part_file, ut_file, growing_file))
        
    async def _simulate_async(self, part_file, ut_file, growing_file):
        """Асинхронная имитация процесса загрузки"""
        
        # Ждем 3 секунды
        await asyncio.sleep(3)
        print("⏰ Через 3 секунды...")
        
        # Увеличиваем размер "растущего" файла
        with open(growing_file, 'ab') as f:
            f.write(b"0" * (50 * 1024 * 1024))  # +50 МБ
        print(f"📈 Увеличен размер: {growing_file.name}")
        
        # Ждем еще 5 секунд
        await asyncio.sleep(5)
        print("⏰ Через 8 секунд...")
        
        # Переименовываем .part файл (завершение загрузки)
        completed_file = part_file.with_suffix('')
        part_file.rename(completed_file)
        print(f"✅ Завершена загрузка: {part_file.name} -> {completed_file.name}")
        
        # Ждем еще 3 секунды
        await asyncio.sleep(3)
        print("⏰ Через 11 секунд...")
        
        # Переименовываем .!ut файл
        completed_ut = ut_file.with_suffix('')
        ut_file.rename(completed_ut)
        print(f"✅ Завершена загрузка: {ut_file.name} -> {completed_ut.name}")
        
        # Ждем еще 8 секунд для стабилизации
        await asyncio.sleep(8)
        print("⏰ Через 19 секунд - проверяем финальные статусы...")
        
        # Показываем финальные статусы
        self.show_final_status()
        
    def show_final_status(self):
        """Показать финальные статусы всех файлов"""
        print("\n📋 Финальные статусы файлов:")
        print("=" * 50)
        
        all_files = self.monitor.get_all_files()
        for file_path, info in all_files.items():
            status_emoji = {
                DownloadStatus.DOWNLOADING: "⬇️",
                DownloadStatus.COMPLETED: "✅",
                DownloadStatus.UNKNOWN: "❓",
                DownloadStatus.FAILED: "❌",
                DownloadStatus.PAUSED: "⏸️"
            }
            
            print(f"{status_emoji.get(info.status, '❓')} {info.file_path.name}")
            print(f"   Статус: {info.status.value}")
            print(f"   Размер: {info.size / (1024*1024):.1f} МБ")
            print(f"   Метод: {info.detection_method}")
            print(f"   Стабильность: {info.stable_duration:.1f}с")
            print()
            
        # Статистика
        downloading = len(self.monitor.get_downloading_files())
        completed = len(self.monitor.get_completed_files())
        
        print(f"📊 Статистика:")
        print(f"   Загружается: {downloading}")
        print(f"   Завершено: {completed}")
        print(f"   Всего: {len(all_files)}")
        
    def cleanup(self):
        """Очистка тестовых файлов"""
        print("\n🧹 Очистка тестовых файлов...")
        self.monitor.stop_monitoring()
        
        try:
            import shutil
            if self.test_dir.exists():
                shutil.rmtree(self.test_dir)
                print(f"✅ Удалена директория: {self.test_dir}")
        except Exception as e:
            print(f"⚠️ Ошибка очистки: {e}")


async def main():
    """Главная функция тестирования"""
    print("🚀 Тестирование системы мониторинга загрузок")
    print("=" * 60)
    
    tester = DownloadMonitorTester()
    
    try:
        # Создаем тестовые файлы
        test_files = tester.create_test_files()
        
        # Запускаем имитацию
        simulation_task = tester.simulate_download_completion(test_files)
        
        # Ждем завершения имитации
        await simulation_task
        
        print("\n✅ Тестирование завершено успешно!")
        
    except KeyboardInterrupt:
        print("\n⏹️ Тестирование прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        logger.error(f"Ошибка в тестировании: {e}")
    finally:
        # Очистка
        tester.cleanup()


if __name__ == '__main__':
    print("Для запуска тестирования нажмите Enter, для выхода - Ctrl+C")
    try:
        input()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nВыход...")
