import asyncio
from pathlib import Path
from typing import Optional, Dict
from .logger import logger
from .html_visual_generator import HtmlVisualGenerator

# Для Telegram уведомлений
try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    

class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = None
        
        # Используем HTML генератор
        self.html_generator = HtmlVisualGenerator(temp_dir="temp")

        if TELEGRAM_AVAILABLE:
            try:
                self.bot = Bot(token=bot_token)
                logger.info("Telegram бот инициализирован")
            except Exception as e:
                logger.error(f"Ошибка инициализации Telegram бота: {e}")

    async def send_message(self, text: str, parse_mode: str = 'HTML'):
        """Отправка сообщения"""
        if not self.bot:
            return False

        try:
            # Разбиваем длинные сообщения
            max_length = 4096
            if len(text) <= max_length:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode
                )
            else:
                # Разбиваем на части
                parts = [text[i:i + max_length] for i in range(0, len(text), max_length)]
                for part in parts:
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=part,
                        parse_mode=parse_mode
                    )
                    await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями

            return True
        except Exception as e:
            logger.error(f"Ошибка отправки Telegram сообщения: {e}")
            return False

    async def send_file(self, file_path: Path, caption: str = None):
        """Отправка файла"""
        if not self.bot or not file_path.exists():
            return False

        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_document(
                    chat_id=self.chat_id,
                    document=f,
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки файла в Telegram: {e}")
            return False

    async def send_photo(self, file_path: Path, caption: str = None):
        """Отправка изображения"""
        if not self.bot or not file_path.exists():
            return False

        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=f,
                    caption=caption,
                    parse_mode='HTML'
                )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки изображения в Telegram: {e}")
            return False

    async def send_file_info_notification(self, file_info: Dict, message: str = None):
        """Отправка уведомления с визуальной карточкой файла"""
        try:
            # Добавляем заголовок в данные файла для кастомизации карточки
            if message and "🔄" in message:
                file_info['title'] = "🔄 Начинаем обработку"
            elif message and "📁" in message:
                file_info['title'] = "📁 Информация о файле"
            
            # Генерируем визуальную карточку
            image_path = self.html_generator.generate_file_info_card(file_info)
            
            if image_path and image_path.exists():
                # Отправляем изображение с подписью
                caption = message or f"📁 Информация о файле: {file_info.get('name', 'Неизвестно')}"
                success = await self.send_photo(image_path, caption)
                
                # Удаляем временный файл
                try:
                    image_path.unlink()
                except:
                    pass
                
                return success
            else:
                # Если не удалось создать изображение, отправляем текстовое сообщение
                if message:
                    return await self.send_message(message)
                return False
                
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления с карточкой файла: {e}")
            # Fallback к текстовому сообщению
            if message:
                return await self.send_message(message)
            return False

    async def send_conversion_notification(self, conversion_info: Dict, message: str = None):
        """Отправка уведомления о конвертации с визуальной карточкой"""
        try:
            # Генерируем карточку конвертации
            image_path = self.html_generator.generate_conversion_card(conversion_info)
            
            if image_path and image_path.exists():
                # Определяем подпись на основе статуса
                status = conversion_info.get('status', 'unknown')
                if not message:
                    if status == 'success':
                        message = f"✅ Конвертация завершена успешно"
                    elif status == 'error':
                        message = f"❌ Ошибка при конвертации"
                    else:
                        message = f"🔄 Конвертация в процессе"
                
                success = await self.send_photo(image_path, message)
                
                # Удаляем временный файл
                try:
                    image_path.unlink()
                except:
                    pass
                
                return success
            else:
                # Fallback к текстовому сообщению
                if message:
                    return await self.send_message(message)
                return False
                
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления о конвертации: {e}")
            if message:
                return await self.send_message(message)
            return False

    async def send_directory_summary_notification(self, summary_info: Dict, message: str = None):
        """Отправка сводки по директории с визуальной карточкой"""
        try:
            # Генерируем сводную карточку
            image_path = self.html_generator.generate_summary_card(summary_info)
            
            if image_path and image_path.exists():
                caption = message or "📊 Сводка по обработанным файлам"
                success = await self.send_photo(image_path, caption)
                
                # Удаляем временный файл
                try:
                    image_path.unlink()
                except:
                    pass
                
                return success
            else:
                # Fallback к текстовому сообщению
                if message:
                    return await self.send_message(message)
                return False
                
        except Exception as e:
            logger.error(f"Ошибка отправки сводки: {e}")
            if message:
                return await self.send_message(message)
            return False

    def cleanup_temp_files(self):
        """Очистка временных файлов"""
        try:
            self.html_generator.cleanup_temp_files()
        except Exception as e:
            logger.error(f"Ошибка очистки временных файлов: {e}")