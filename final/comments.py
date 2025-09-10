from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import COMMENTS_PER_PAGE, CHANNEL_ID, BOT_USERNAME
from utils import escape_markdown_text
from db import get_comment_count
from submission import is_media_post, get_media_info
from db_connection import get_db_connection, execute_query, adapt_query
import logging

logger = logging.getLogger(__name__)

def save_comment(post_id, content, user_id, parent_comment_id=None):
    """Save a comment to the database"""
    try:
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            
            # First, validate that the post exists
            post_check_query = adapt_query("SELECT post_id FROM posts WHERE post_id = ? AND approved = 1")
            cursor.execute(post_check_query, (post_id,))
            post_exists = cursor.fetchone()
            
            if not post_exists:
                logger.error(f"Cannot save comment: Post {post_id} does not exist or is not approved")
                return None, f"Post {post_id} not found or not approved"
            
            # Validate parent comment if provided
            if parent_comment_id:
                parent_check_query = adapt_query("SELECT comment_id FROM comments WHERE comment_id = ?")
                cursor.execute(parent_check_query, (parent_comment_id,))
                parent_exists = cursor.fetchone()
                
                if not parent_exists:
                    logger.error(f"Cannot save comment: Parent comment {parent_comment_id} does not exist")
                    return None, f"Parent comment {parent_comment_id} not found"
            
            # Insert comment using proper database abstraction
            if db_conn.use_postgresql:
                # PostgreSQL: use RETURNING clause to get the ID
                insert_query = adapt_query("INSERT INTO comments (post_id, content, user_id, parent_comment_id) VALUES (?, ?, ?, ?) RETURNING comment_id")
                cursor.execute(insert_query, (post_id, content, user_id, parent_comment_id))
                comment_id = cursor.fetchone()[0]
            else:
                # SQLite: use lastrowid
                insert_query = adapt_query("INSERT INTO comments (post_id, content, user_id, parent_comment_id) VALUES (?, ?, ?, ?)")
                cursor.execute(insert_query, (post_id, content, user_id, parent_comment_id))
                comment_id = cursor.lastrowid

            # Update user stats
            update_query = adapt_query("UPDATE users SET comments_posted = comments_posted + 1 WHERE user_id = ?")
            cursor.execute(update_query, (user_id,))
            
            if db_conn.use_postgresql:
                conn.commit()
            
            return comment_id, None
    except Exception as e:
        logger.error(f"Error saving comment: {e}")
        return None, f"Database error: {str(e)}"

def get_post_with_channel_info(post_id):
    """Get post information including channel message ID"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(
            f"SELECT post_id, content, category, channel_message_id, approved FROM posts WHERE post_id = {placeholder}",
            (post_id,)
        )
        return cursor.fetchone()

def get_comments_paginated(post_id, page=1):
    """Get comments for a post in flat structure like Telegram native replies"""
    offset = (page - 1) * COMMENTS_PER_PAGE

    try:
        # Get total count using the existing function
        total_comments = get_comment_count(post_id)

        # Get paginated comments in flat structure
        db_conn = get_db_connection()
        
        if db_conn.use_postgresql:
            # PostgreSQL version with ROW_NUMBER()
            query = f"""
                SELECT comment_id, content, timestamp, likes, dislikes, flagged, parent_comment_id,
                       ROW_NUMBER() OVER (ORDER BY timestamp ASC) as comment_number
                FROM comments 
                WHERE post_id = {db_conn.get_placeholder()}
                ORDER BY timestamp ASC
                LIMIT {db_conn.get_placeholder()} OFFSET {db_conn.get_placeholder()}
            """
        else:
            # SQLite version with ROW_NUMBER()
            query = f"""
                SELECT comment_id, content, timestamp, likes, dislikes, flagged, parent_comment_id,
                       ROW_NUMBER() OVER (ORDER BY timestamp ASC) as comment_number
                FROM comments 
                WHERE post_id = {db_conn.get_placeholder()}
                ORDER BY timestamp ASC
                LIMIT {db_conn.get_placeholder()} OFFSET {db_conn.get_placeholder()}
            """
        
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (post_id, COMMENTS_PER_PAGE, offset))
            comments = cursor.fetchall()

            # Transform into simplified flat structure
            comments_flat = []
            for comment in comments or []:
                comment_id = comment[0]
                content = comment[1]
                timestamp = comment[2]
                likes = comment[3]
                dislikes = comment[4]
                flagged = comment[5]
                parent_comment_id = comment[6]
                comment_number = comment[7]
                
                comment_data = {
                    'comment_id': comment_id,
                    'content': content,
                    'timestamp': timestamp,
                    'likes': likes,
                    'dislikes': dislikes,
                    'flagged': flagged,
                    'parent_comment_id': parent_comment_id,
                    'comment_number': comment_number,
                    'is_reply': parent_comment_id is not None
                }
                
                # If this is a reply, get the original comment info
                if parent_comment_id:
                    placeholder = db_conn.get_placeholder()
                    cursor.execute(
                        f"SELECT comment_id, content, timestamp FROM comments WHERE comment_id = {placeholder}",
                        (parent_comment_id,)
                    )
                    original = cursor.fetchone()
                    if original:
                        comment_data['original_comment'] = {
                            'comment_id': original[0],
                            'content': original[1],
                            'timestamp': original[2]
                        }
                
                comments_flat.append(comment_data)

            total_pages = (total_comments + COMMENTS_PER_PAGE - 1) // COMMENTS_PER_PAGE

            return comments_flat, page, total_pages, total_comments
    except Exception as e:
        print(f"Error getting paginated comments: {e}")
        return [], 1, 1, 0

def get_comment_by_id(comment_id):
    """Get a specific comment by ID"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(
            f"SELECT * FROM comments WHERE comment_id = {placeholder}",
            (comment_id,)
        )
        return cursor.fetchone()

def react_to_comment(user_id, comment_id, reaction_type):
    """Add or update reaction to a comment"""
    try:
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            
            # Check existing reaction
            cursor.execute(
                f"SELECT reaction_type FROM reactions WHERE user_id = {placeholder} AND target_type = 'comment' AND target_id = {placeholder}",
                (user_id, comment_id)
            )
            existing = cursor.fetchone()
            
            if existing:
                if existing[0] == reaction_type:
                    # Remove reaction if same type
                    cursor.execute(
                        f"DELETE FROM reactions WHERE user_id = {placeholder} AND target_type = 'comment' AND target_id = {placeholder}",
                        (user_id, comment_id)
                    )
                    # Update comment counts
                    if reaction_type == 'like':
                        cursor.execute(
                            f"UPDATE comments SET likes = likes - 1 WHERE comment_id = {placeholder}",
                            (comment_id,)
                        )
                    else:
                        cursor.execute(
                            f"UPDATE comments SET dislikes = dislikes - 1 WHERE comment_id = {placeholder}",
                            (comment_id,)
                        )
                    action = "removed"
                else:
                    # Update reaction type
                    cursor.execute(
                        f"UPDATE reactions SET reaction_type = {placeholder} WHERE user_id = {placeholder} AND target_type = 'comment' AND target_id = {placeholder}",
                        (reaction_type, user_id, comment_id)
                    )
                    # Update comment counts
                    if existing[0] == 'like':
                        cursor.execute(
                            f"UPDATE comments SET likes = likes - 1, dislikes = dislikes + 1 WHERE comment_id = {placeholder}",
                            (comment_id,)
                        )
                    else:
                        cursor.execute(
                            f"UPDATE comments SET likes = likes + 1, dislikes = dislikes - 1 WHERE comment_id = {placeholder}",
                            (comment_id,)
                        )
                    action = "changed"
            else:
                # Add new reaction
                cursor.execute(
                    f"INSERT INTO reactions (user_id, target_type, target_id, reaction_type) VALUES ({placeholder}, 'comment', {placeholder}, {placeholder})",
                    (user_id, comment_id, reaction_type)
                )
                # Update comment counts
                if reaction_type == 'like':
                    cursor.execute(
                        f"UPDATE comments SET likes = likes + 1 WHERE comment_id = {placeholder}",
                        (comment_id,)
                    )
                else:
                    cursor.execute(
                        f"UPDATE comments SET dislikes = dislikes + 1 WHERE comment_id = {placeholder}",
                        (comment_id,)
                    )
                action = "added"
            
            conn.commit()
            
            # Return current counts along with action
            cursor.execute(
                f"SELECT likes, dislikes FROM comments WHERE comment_id = {placeholder}",
                (comment_id,)
            )
            counts = cursor.fetchone()
            current_likes = counts[0] if counts else 0
            current_dislikes = counts[1] if counts else 0
            
            return True, action, current_likes, current_dislikes
    except Exception as e:
        return False, str(e), 0, 0

def flag_comment(comment_id):
    """Flag a comment for review"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f"UPDATE comments SET flagged = 1 WHERE comment_id = {placeholder}", (comment_id,))
        conn.commit()

def get_user_reaction(user_id, comment_id):
    """Get user's reaction to a specific comment"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(
            f"SELECT reaction_type FROM reactions WHERE user_id = {placeholder} AND target_type = 'comment' AND target_id = {placeholder}",
            (user_id, comment_id)
        )
        result = cursor.fetchone()
        return result[0] if result else None

def get_comment_sequential_number(comment_id):
    """Get the sequential number of a comment within its post"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        
        # First get the comment's post_id and check if it's a reply
        cursor.execute(
            f"SELECT post_id, parent_comment_id FROM comments WHERE comment_id = {placeholder}",
            (comment_id,)
        )
        comment_info = cursor.fetchone()
        
        if not comment_info:
            return None
        
        post_id, parent_comment_id = comment_info
        
        if parent_comment_id:  # This is a reply
            # Get the sequential reply number within the parent comment
            cursor.execute(f"""
                SELECT COUNT(*) FROM comments 
                WHERE parent_comment_id = {placeholder} AND comment_id <= {placeholder}
            """, (parent_comment_id, comment_id))
            result = cursor.fetchone()
            return result[0] if result else 1
        else:  # This is a main comment
            # Get the sequential comment number within the post
            cursor.execute(f"""
                SELECT COUNT(*) FROM comments 
                WHERE post_id = {placeholder} AND parent_comment_id IS NULL AND comment_id <= {placeholder}
            """, (post_id, comment_id))
            result = cursor.fetchone()
            return result[0] if result else 1

def get_parent_comment_for_reply(comment_id):
    """Get the parent comment details for a reply comment"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        
        # Get the reply comment details
        cursor.execute(
            f"SELECT parent_comment_id FROM comments WHERE comment_id = {placeholder}",
            (comment_id,)
        )
        result = cursor.fetchone()
        
        if not result or not result[0]:
            return None  # Not a reply
        
        parent_comment_id = result[0]
        
        # Get the parent comment details
        cursor.execute(
            f"SELECT comment_id, post_id, content, timestamp FROM comments WHERE comment_id = {placeholder}",
            (parent_comment_id,)
        )
        parent_comment = cursor.fetchone()
        
        if parent_comment:
            # Get the sequential number of the parent comment
            parent_sequential_number = get_comment_sequential_number(parent_comment_id)
            return {
                'comment_id': parent_comment[0],
                'post_id': parent_comment[1],
                'content': parent_comment[2],
                'timestamp': parent_comment[3],
                'sequential_number': parent_sequential_number
            }
        
        return None

def get_comment_reply_level(comment_id):
    """Get the reply level of a comment (0 = main comment, 1 = first reply, 2 = second reply)"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        
        # Check if it's a main comment
        cursor.execute(
            f"SELECT parent_comment_id FROM comments WHERE comment_id = {placeholder}",
            (comment_id,)
        )
        result = cursor.fetchone()
        
        if not result or not result[0]:
            return 0  # Main comment
        
        parent_comment_id = result[0]
        
        # Check if parent is a main comment or a reply
        cursor.execute(
            f"SELECT parent_comment_id FROM comments WHERE comment_id = {placeholder}",
            (parent_comment_id,)
        )
        parent_result = cursor.fetchone()
        
        if not parent_result or not parent_result[0]:
            return 1  # First-level reply (reply to main comment)
        else:
            return 2  # Second-level reply (reply to first-level reply)

def get_comment_type_prefix(comment_id):
    """Get the appropriate prefix for a comment based on its reply level"""
    # In flat structure, all comments are just "comment" regardless of level
    return "comment"

# Format replies to look like Telegram's native reply feature
def format_reply(parent_text, child_text, parent_author="Anonymous"):
    """Format reply messages to look like Telegram's native reply feature with blockquote"""
    # Truncate parent text if too long for better display
    if len(parent_text) > 150:
        parent_text = parent_text[:150] + "..."
    
    # Use Telegram's native blockquote styling
    return f"<blockquote expandable>{parent_text}</blockquote>\n\n{child_text}"

def find_comment_page(comment_id):
    """Find which page a comment is on for navigation"""
    try:
        # Get comment info
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            cursor.execute(
                f"SELECT post_id, timestamp FROM comments WHERE comment_id = {placeholder}",
                (comment_id,)
            )
            comment_info = cursor.fetchone()
            
            if not comment_info:
                return None
                
            post_id, timestamp = comment_info
            
            # Count comments before this one (chronological order)
            cursor.execute(f"""
                SELECT COUNT(*) FROM comments 
                WHERE post_id = {placeholder} AND timestamp < {placeholder}
                ORDER BY timestamp ASC
            """, (post_id, timestamp))
            comments_before = cursor.fetchone()[0]
            page = (comments_before // COMMENTS_PER_PAGE) + 1
            
            return {
                'page': page,
                'post_id': post_id,
                'comment_id': comment_id
            }
    except Exception as e:
        print(f"Error finding comment page: {e}")
        return None

async def update_channel_message_comment_count(context, post_id):
    """Update the comment count on the channel message"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get post info including channel message ID and post_number
        db_conn = get_db_connection()
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = db_conn.get_placeholder()
            cursor.execute(
                f"SELECT post_id, content, category, channel_message_id, approved, post_number FROM posts WHERE post_id = {placeholder}",
                (post_id,)
            )
            post_info = cursor.fetchone()
        
        if not post_info or not post_info[3]:  # No channel_message_id
            return False, "No channel message found"
        
        post_id, content, category, channel_message_id, approved, post_number = post_info
        
        if approved != 1:  # Not approved
            return False, "Post not approved"
        
        # Get current comment count
        comment_count = get_comment_count(post_id)
        
        # Create updated inline buttons with new comment count
        # Strip @ symbol from BOT_USERNAME for URL
        bot_username_clean = BOT_USERNAME.lstrip('@')
        keyboard = [
            [
                InlineKeyboardButton(
                    "💬 Add Comment", 
                    url=f"https://t.me/{bot_username_clean}?start=comment_{post_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"👀 See Comments ({comment_count})", 
                    url=f"https://t.me/{bot_username_clean}?start=view_{post_id}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # ✅ Preserve the original post structure format exactly like approval.py
        # Convert categories into hashtags
        categories_text = " ".join(
            [f"#{cat.strip().replace(' ', '')}" for cat in category.split(",")]
        )
        
        # Check if this is a media post
        if is_media_post(post_id):
            # Get media information
            media_info = get_media_info(post_id)
            
            if media_info:
                # Prepare caption with post number, text content, and hashtags (same as approval.py)
                caption_text = f"<b>Confess # {post_number}</b>"
                
                # Add text content if available
                if content and content.strip():
                    caption_text += f"\n\n{content}"
                
                # Add media caption if available and different from main content
                if media_info.get('caption') and media_info['caption'] != content:
                    caption_text += f"\n\n{media_info['caption']}"
                
                # Add hashtags
                caption_text += f"\n\n{categories_text}"
                
                # Update media message caption
                await context.bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=channel_message_id,
                    caption=caption_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            else:
                # Media info not found, try as text message fallback
                await context.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=channel_message_id,
                    text=f"<b>Confess # {post_number}</b>\n\n{content}\n\n{categories_text}",
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
        else:
            # Text-only post - use edit_message_text
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=channel_message_id,
                text=f"<b>Confess # {post_number}</b>\n\n{content}\n\n{categories_text}",
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        
        return True, f"Updated comment count to {comment_count}"
    
    except Exception as e:
        return False, f"Failed to update channel message: {str(e)}"
