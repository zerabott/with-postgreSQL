import logging
from config import ADMIN_IDS
from db_connection import get_db_connection
from utils import escape_markdown_text

logger = logging.getLogger(__name__)

def save_user_message(user_id, message):
    """Save user message to admin"""
    try:
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            cursor.execute(
                f"INSERT INTO admin_messages (user_id, user_message) VALUES ({placeholder}, {placeholder})",
                (user_id, message)
            )
            
            # Get the inserted message ID
            if db_conn.use_postgresql:
                cursor.execute("SELECT lastval()")
                message_id = cursor.fetchone()[0]
            else:
                message_id = cursor.lastrowid
                
            conn.commit()
            return message_id, None
    except Exception as e:
        return None, f"Database error: {str(e)}"

def save_admin_reply(message_id, admin_id, reply):
    """Save admin reply to user message"""
    try:
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            cursor.execute(
                f"UPDATE admin_messages SET admin_reply = {placeholder}, admin_id = {placeholder}, replied = 1 WHERE message_id = {placeholder}",
                (reply, admin_id, message_id)
            )
            conn.commit()
            return True
    except Exception as e:
        return False

def get_pending_messages():
    """Get all pending user messages for admins"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT message_id, user_id, user_message, timestamp
            FROM admin_messages 
            WHERE replied = 0 
            ORDER BY timestamp ASC
        ''')
        return cursor.fetchall()

def get_message_by_id(message_id):
    """Get specific message by ID"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(
            f"SELECT * FROM admin_messages WHERE message_id = {placeholder}",
            (message_id,)
        )
        return cursor.fetchone()

async def send_message_to_admins(context, user_id, message):
    """Send user message to all admins with inline reply buttons"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    logger.info(f"Attempting to send message from user {user_id} to admins")
    
    message_id, error = save_user_message(user_id, message)
    
    if error:
        logger.error(f"Error saving message: {error}")
        return False, error
    
    logger.info(f"Message saved with ID: {message_id}")
    
    import datetime
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    admin_text = f"""
📨 *New User Message*

*Message ID:* \\#{message_id}
*From User:* {user_id}
*Timestamp:* {escape_markdown_text(current_time)}

*Message:*
{escape_markdown_text(message)}

*Reply Options:*
• Use the buttons below for quick reply
• Or use: `/reply {message_id} <your_response>`
"""
    
    # Create inline keyboard for admin actions
    keyboard = [
        [
            InlineKeyboardButton("💬 Quick Reply", callback_data=f"admin_reply_{message_id}"),
            InlineKeyboardButton("📋 View History", callback_data=f"admin_history_{user_id}")
        ],
        [
            InlineKeyboardButton("✅ Mark as Read", callback_data=f"admin_read_{message_id}"),
            InlineKeyboardButton("🔇 Ignore User", callback_data=f"admin_ignore_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    success_count = 0
    
    # Ensure there are admins in the list
    if not ADMIN_IDS:
        logger.warning("No admins configured!")
        return False, "No admins configured"
    
    logger.info(f"Sending to {len(ADMIN_IDS)} admin(s)")
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2"
            )
            success_count += 1
            logger.info(f"Successfully sent to admin {admin_id}")
        except Exception as e:
            logger.error(f"Failed to send to admin {admin_id}: {e}")
    
    logger.info(f"Total successful sends: {success_count}")
    return success_count > 0, f"Sent to {success_count} admins"

async def send_admin_reply_to_user(context, message_id, admin_id, reply):
    """Send admin reply to user anonymously"""
    message_data = get_message_by_id(message_id)
    
    if not message_data:
        return False, "Message not found"
    
    user_id = message_data[1]  # user_id is at index 1
    
    # Save the reply
    if not save_admin_reply(message_id, admin_id, reply):
        return False, "Failed to save reply"
    
    # Send to user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"""
📧 *Admin Reply*

{escape_markdown_text(reply)}

This is an anonymous reply from the administration team\\.
If you need to respond, use "📞 Contact Admin" again\\.
""",
            parse_mode="MarkdownV2"
        )
        return True, "Reply sent successfully"
    except Exception as e:
        return False, f"Failed to send reply: {str(e)}"

def mark_message_as_read(message_id):
    """Mark a message as read/handled"""
    try:
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            cursor.execute(
                f"UPDATE admin_messages SET replied = 1 WHERE message_id = {placeholder}",
                (message_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error marking message as read: {e}")
        return False

def ignore_user_messages(user_id):
    """Mark all messages from a user as ignored/handled"""
    try:
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            cursor.execute(
                f"UPDATE admin_messages SET replied = 1 WHERE user_id = {placeholder} AND replied = 0",
                (user_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error ignoring user messages: {e}")
        return False

def get_user_message_history(user_id, limit=10):
    """Get user's message history with admins - fixed version"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f'''
            SELECT message_id, user_message, timestamp, replied, admin_reply
            FROM admin_messages 
            WHERE user_id = {placeholder} 
            ORDER BY timestamp DESC 
            LIMIT {placeholder}
        ''', (user_id, limit))
        return cursor.fetchall()
