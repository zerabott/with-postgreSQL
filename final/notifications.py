"""
Smart Notifications System for University Confession Bot
Features: Personalized notifications, category subscriptions, trending alerts, daily digest
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import psycopg2 # Added this import

from db_connection import get_db, get_db_connection, adapt_query
from config import CATEGORIES
from utils import escape_markdown_text, truncate_text

logger = logging.getLogger(__name__)

class NotificationEngine:
    def __init__(self):
        self.init_notification_tables()
    
    def init_notification_tables(self):
        """Initialize notification-related database tables"""
        db_conn = get_db_connection()
        use_pg = getattr(db_conn, "use_postgresql", False)

        with get_db() as conn:
            cursor = conn.cursor()
            try:
                # User notification preferences
                if use_pg:
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS notification_preferences (
                            user_id BIGINT PRIMARY KEY,
                            comment_notifications BOOLEAN DEFAULT TRUE,
                            favorite_categories TEXT DEFAULT '',
                            daily_digest BOOLEAN DEFAULT TRUE,
                            trending_alerts BOOLEAN DEFAULT TRUE,
                            digest_time TEXT DEFAULT '18:00',
                            notification_history TEXT DEFAULT '[]'
                        )''')
                else: # SQLite
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS notification_preferences (
                            user_id INTEGER PRIMARY KEY,
                            comment_notifications BOOLEAN DEFAULT TRUE,
                            favorite_categories TEXT DEFAULT '',
                            daily_digest BOOLEAN DEFAULT TRUE,
                            trending_alerts BOOLEAN DEFAULT TRUE,
                            digest_time TEXT DEFAULT '18:00',
                            notification_history TEXT DEFAULT '[]'
                        )''')
                
                # Table for post subscriptions (for comments)
                if use_pg:
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS post_subscriptions (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            post_id INT NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, post_id)
                        )''')
                else: # SQLite
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS post_subscriptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            post_id INTEGER NOT NULL,
                            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, post_id)
                        )''')

                # Table to store which posts have been notified for trending
                if use_pg:
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS trending_notifications (
                            post_id INT PRIMARY KEY,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')
                else: # SQLite
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS trending_notifications (
                            post_id INTEGER PRIMARY KEY,
                            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                        )''')
                
                conn.commit()

            except (sqlite3.OperationalError, psycopg2.errors.InFailedSqlTransaction, psycopg2.errors.SyntaxError) as e:
                logger.error(f"Failed to initialize notifications tables, rolling back: {e}")
                conn.rollback() # Rollback to clear aborted transaction state
                raise e # Re-raise the exception to stop the bot from running with a bad DB state
            except Exception as e:
                logger.error(f"An unexpected error occurred during table initialization, rolling back: {e}")
                conn.rollback()
                raise e
    
    def get_user_preferences(self, user_id: int) -> dict:
        """Get or create user notification preferences"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            cursor.execute(f'''
                SELECT comment_notifications, favorite_categories, daily_digest, trending_alerts, digest_time, notification_history
                FROM notification_preferences WHERE user_id = {placeholder}
            ''', (user_id,))
            
            result = cursor.fetchone()
            
            if result:
                # Assuming favorite_categories and notification_history are stored as JSON strings
                return {
                    'comment_notifications': bool(result[0]),
                    'favorite_categories': eval(result[1]) if result[1] else [],
                    'daily_digest': bool(result[2]),
                    'trending_alerts': bool(result[3]),
                    'digest_time': result[4],
                    'notification_history': eval(result[5]) if result[5] else []
                }
            else:
                # Create default preferences for new user
                default_prefs = {
                    'comment_notifications': True,
                    'favorite_categories': '[]',
                    'daily_digest': True,
                    'trending_alerts': True,
                    'digest_time': '18:00',
                    'notification_history': '[]'
                }
                
                if db_conn.use_postgresql:
                    insert_query = f'''
                        INSERT INTO notification_preferences (user_id, comment_notifications, favorite_categories, daily_digest, trending_alerts, digest_time, notification_history)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    '''
                    cursor.execute(insert_query, (
                        user_id,
                        default_prefs['comment_notifications'],
                        default_prefs['favorite_categories'],
                        default_prefs['daily_digest'],
                        default_prefs['trending_alerts'],
                        default_prefs['digest_time'],
                        default_prefs['notification_history']
                    ))
                else: # SQLite
                    insert_query = f'''
                        INSERT INTO notification_preferences (user_id, comment_notifications, favorite_categories, daily_digest, trending_alerts, digest_time, notification_history)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    '''
                    cursor.execute(insert_query, (
                        user_id,
                        int(default_prefs['comment_notifications']),
                        default_prefs['favorite_categories'],
                        int(default_prefs['daily_digest']),
                        int(default_prefs['trending_alerts']),
                        default_prefs['digest_time'],
                        default_prefs['notification_history']
                    ))
                
                conn.commit()
                return {
                    'comment_notifications': True,
                    'favorite_categories': [],
                    'daily_digest': True,
                    'trending_alerts': True,
                    'digest_time': '18:00',
                    'notification_history': []
                }
    
    def update_user_preferences(self, user_id: int, updates: dict):
        """Update user notification preferences"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            set_clauses = []
            values = []
            
            for key, value in updates.items():
                set_clauses.append(f"{key} = {placeholder}")
                if isinstance(value, list) or isinstance(value, dict):
                    values.append(str(value)) # Store as JSON string
                elif isinstance(value, bool):
                    values.append(int(value)) # Store as integer
                else:
                    values.append(value)
            
            values.append(user_id)
            
            set_clause_str = ", ".join(set_clauses)
            
            cursor.execute(f'''
                UPDATE notification_preferences SET {set_clause_str} WHERE user_id = {placeholder}
            ''', tuple(values))
            
            conn.commit()

    def subscribe_to_post(self, user_id: int, post_id: int):
        """Subscribe a user to a post for comment notifications"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            if db_conn.use_postgresql:
                insert_query = f'''
                    INSERT INTO post_subscriptions (user_id, post_id, timestamp)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, post_id) DO NOTHING
                '''
                cursor.execute(insert_query, (user_id, post_id))
            else: # SQLite
                insert_query = f'''
                    INSERT OR IGNORE INTO post_subscriptions (user_id, post_id, timestamp)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                '''
                cursor.execute(insert_query, (user_id, post_id))
            
            conn.commit()

    def unsubscribe_from_post(self, user_id: int, post_id: int):
        """Unsubscribe a user from a post"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            cursor.execute(f'''
                DELETE FROM post_subscriptions WHERE user_id = {placeholder} AND post_id = {placeholder}
            ''', (user_id, post_id))
            
            conn.commit()
    
    def get_subscribed_users(self, post_id: int) -> List[int]:
        """Get all users subscribed to a post"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            cursor.execute(f'SELECT user_id FROM post_subscriptions WHERE post_id = {placeholder}', (post_id,))
            return [row[0] for row in cursor.fetchall()]

    def is_subscribed_to_post(self, user_id: int, post_id: int) -> bool:
        """Check if a user is subscribed to a specific post"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            cursor.execute(f'SELECT 1 FROM post_subscriptions WHERE user_id = {placeholder} AND post_id = {placeholder}', (user_id, post_id))
            return cursor.fetchone() is not None

    def get_users_with_favorite_category(self, category: str) -> List[int]:
        """Get users who have a specific category as a favorite"""
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            if db_conn.use_postgresql:
                cursor.execute(f'''
                    SELECT user_id FROM notification_preferences
                    WHERE favorite_categories LIKE {placeholder} OR favorite_categories LIKE {placeholder} OR favorite_categories LIKE {placeholder}
                ''', (f'%"{category}"%', f'%"{category}",%', f'%,"{category}"%'))
            else: # SQLite
                 cursor.execute(f'''
                    SELECT user_id FROM notification_preferences
                    WHERE favorite_categories LIKE {placeholder}
                ''', (f'%"{category}"%'))
            
            return [row[0] for row in cursor.fetchall()]
    
    def get_daily_digest_users(self) -> List[int]:
        """Get users who have daily digest enabled and have not yet received a digest for today"""
        # This is a placeholder and should be implemented with a proper tracking mechanism
        db_conn = get_db_connection()
        with get_db() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            
            cursor.execute(f'''
                SELECT user_id FROM notification_preferences WHERE daily_digest = {placeholder} AND digest_time <= {placeholder}
            ''', (1, now.strftime('%H:%M')))
            return [row[0] for row in cursor.fetchall()]

# Utility functions for sending notifications (these need to be implemented)
async def send_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None):
    """Send a notification message to a user"""
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send notification to user {user_id}: {e}")
        return False

async def notify_comment_on_post(context: ContextTypes.DEFAULT_TYPE, post_id: int, post_author_id: int, comment_author_id: int):
    """Notify users who are subscribed to a post about a new comment"""
    logger.info(f"Notifying users about new comment on post {post_id}")
    
    subscribed_users = notification_engine.get_subscribed_users(post_id)
    post_author_info = get_user_info(post_author_id)
    
    for user_id in subscribed_users:
        if user_id == comment_author_id:
            continue # Don't notify the commenter themselves

        try:
            # Check if user has comment notifications enabled
            prefs = notification_engine.get_user_preferences(user_id)
            if not prefs.get('comment_notifications', True):
                continue

            notification_text = f"💬 A new comment has been posted on a confession you are following. [Click here to view](tg://post?id={post_id})"
            
            await send_notification(context, user_id, notification_text)
            logger.info(f"Sent comment notification for post {post_id} to user {user_id}")
        except Exception as e:
            logger.error(f"Error sending comment notification for post {post_id} to user {user_id}: {e}")

async def notify_favorite_category_post(context: ContextTypes.DEFAULT_TYPE, post_id: int, category: str):
    """Notify users who have a specific category as a favorite"""
    logger.info(f"Notifying users about new post in favorite category {category}")

    users = notification_engine.get_users_with_favorite_category(category)
    
    notification_text = f"🌟 A new post in your favorite category, `{escape_markdown_text(category)}`, has been published! [Click to view](tg://post?id={post_id})"
    
    for user_id in users:
        await send_notification(context, user_id, notification_text)

async def notify_trending_post(context: ContextTypes.DEFAULT_TYPE, post_id: int):
    """Notify users about a trending post"""
    logger.info(f"Notifying users about trending post {post_id}")
    # Implementation depends on how you define "trending"
    # Placeholder: find users with trending alerts on and send a message

async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """Send daily digest of top posts to users"""
    logger.info("Sending daily digest")
    # Implementation depends on how you get the top posts and which users to send to

# User preference management handlers
async def show_notification_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the user their notification settings"""
    user_id = update.effective_user.id
    prefs = notification_engine.get_user_preferences(user_id)

    settings_text = f"""
*🔔 Notification Settings*

Here you can customize how you receive updates:

• *New Comments on Your Posts:* {'✅ On' if prefs['comment_notifications'] else '❌ Off'}
• *Daily Digest of Top Posts:* {'✅ On' if prefs['daily_digest'] else '❌ Off'}
• *Trending Alerts:* {'✅ On' if prefs['trending_alerts'] else '❌ Off'}
• *Favorite Categories:* {', '.join(prefs['favorite_categories']) if prefs['favorite_categories'] else 'None'}
• *Daily Digest Time:* `{prefs['digest_time']}`
"""
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'🔕' if prefs['comment_notifications'] else '🔔'} Comments on Your Posts",
                callback_data="toggle_comment_notifications"
            ),
            InlineKeyboardButton(
                f"{'🔕' if prefs['daily_digest'] else '🔔'} Daily Digest",
                callback_data="toggle_daily_digest"
            )
        ],
        [
            InlineKeyboardButton(f"⏰ Change Digest Time", callback_data="set_digest_time")
        ],
        [
            InlineKeyboardButton(
                f"{'🔕' if prefs['trending_alerts'] else '🔥'} Trending Alerts",
                callback_data="toggle_trending"
            )
        ],
        [
            InlineKeyboardButton("❤️ Manage Favorite Categories", callback_data="manage_categories")
        ],
        [
            InlineKeyboardButton("📊 Notification History", callback_data="notification_history"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(
            settings_text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(
            settings_text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )

# Export functions for use in other modules
__all__ = [
    'notification_engine',
    'get_user_preferences',
    'update_user_preferences',
    'subscribe_to_post',
    'unsubscribe_from_post',
    'send_notification',
    'notify_comment_on_post',
    'notify_favorite_category_post',
    'notify_trending_post',
    'send_daily_digest',
    'show_notification_settings'
]
