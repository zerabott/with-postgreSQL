import sqlite3
import datetime
from config import DB_PATH
from db_connection import get_db_connection
import logging

logger = logging.getLogger(__name__)

# Keep backward compatibility
def get_db():
    """Get database connection (backward compatibility)"""
    db_conn = get_db_connection()
    return db_conn.get_connection()

def init_db():
    """Initialize database with enhanced schema"""
    db_conn = get_db_connection()
    use_pg = getattr(db_conn, "use_postgresql", False)

    with db_conn.get_connection() as conn:
        cursor = conn.cursor()

        # Users table
        if use_pg:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                questions_asked INT DEFAULT 0,
                comments_posted INT DEFAULT 0,
                blocked INT DEFAULT 0
            )''')
        else:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TEXT DEFAULT CURRENT_TIMESTAMP,
                questions_asked INTEGER DEFAULT 0,
                comments_posted INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0
            )''')

        # Posts table
        if use_pg:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                post_id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id BIGINT NOT NULL,
                approved INT DEFAULT NULL,
                channel_message_id INT,
                flagged INT DEFAULT 0,
                likes INT DEFAULT 0,
                post_number INT DEFAULT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
        else:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL,
                approved INTEGER DEFAULT NULL,
                channel_message_id INTEGER,
                flagged INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                post_number INTEGER DEFAULT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')

        # Comments table
        if use_pg:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                comment_id SERIAL PRIMARY KEY,
                post_id INT NOT NULL,
                user_id BIGINT NOT NULL,
                content TEXT NOT NULL,
                parent_comment_id INT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                likes INT DEFAULT 0,
                dislikes INT DEFAULT 0,
                flagged INT DEFAULT 0,
                FOREIGN KEY(post_id) REFERENCES posts(post_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(parent_comment_id) REFERENCES comments(comment_id)
            )''')
        else:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                parent_comment_id INTEGER,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                likes INTEGER DEFAULT 0,
                dislikes INTEGER DEFAULT 0,
                flagged INTEGER DEFAULT 0,
                FOREIGN KEY(post_id) REFERENCES posts(post_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(parent_comment_id) REFERENCES comments(comment_id)
            )''')

        # Reactions table
        if use_pg:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reactions (
                reaction_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INT NOT NULL,
                reaction_type TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, target_type, target_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
        else:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reactions (
                reaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                reaction_type TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, target_type, target_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')

        # Reports table
        if use_pg:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INT NOT NULL,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
        else:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                reason TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')

        # Admin messages table
        if use_pg:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_messages (
                message_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                admin_id BIGINT,
                user_message TEXT,
                admin_reply TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                replied INT DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
        else:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                admin_id INTEGER,
                user_message TEXT,
                admin_reply TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                replied INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')

        # Ranking system tables
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_rankings (
            user_id INTEGER PRIMARY KEY,
            total_points INTEGER DEFAULT 0,
            weekly_points INTEGER DEFAULT 0,
            monthly_points INTEGER DEFAULT 0,
            current_rank_id INTEGER DEFAULT 1,
            rank_progress REAL DEFAULT 0.0,
            total_achievements INTEGER DEFAULT 0,
            highest_rank_achieved INTEGER DEFAULT 1,
            consecutive_days INTEGER DEFAULT 0,
            last_login_date TEXT,
            last_activity TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS point_transactions (
            transaction_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            points_change INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            reference_id INTEGER,
            reference_type TEXT,
            description TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_achievements (
            achievement_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            achievement_type TEXT NOT NULL,
            achievement_name TEXT NOT NULL,
            achievement_description TEXT,
            points_awarded INTEGER DEFAULT 0,
            is_special INTEGER DEFAULT 0,
            metadata TEXT,
            achieved_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS rank_definitions (
            rank_id SERIAL PRIMARY KEY,
            rank_name TEXT NOT NULL,
            rank_emoji TEXT NOT NULL,
            min_points INTEGER NOT NULL,
            max_points INTEGER,
            special_perks TEXT,
            is_special INTEGER DEFAULT 0
        )''')
        
        # Check if rank_definitions table has the correct columns before inserting
        try:
            # Test if the table has the correct schema by attempting to select from min_points
            cursor.execute("SELECT min_points FROM rank_definitions LIMIT 1")
            
            # If we get here, the table has the correct schema, so insert default rank definitions
            cursor.execute('''
            INSERT OR IGNORE INTO rank_definitions (rank_id, rank_name, rank_emoji, min_points, max_points, special_perks, is_special)
            VALUES 
                (1, 'Freshman', '🥉', 0, 99, '{}', 0),
                (2, 'Sophomore', '🥈', 100, 249, '{}', 0),
                (3, 'Junior', '🥇', 250, 499, '{}', 0),
                (4, 'Senior', '🏆', 500, 999, '{"daily_confessions": 8}', 0),
                (5, 'Graduate', '🎓', 1000, 1999, '{"daily_confessions": 10, "priority_review": true}', 0),
                (6, 'Master', '👑', 2000, 4999, '{"daily_confessions": 15, "priority_review": true, "comment_highlight": true}', 1),
                (7, 'Legend', '🌟', 5000, NULL, '{"all_perks": true, "unlimited_daily": true, "legend_badge": true}', 1)
            ''')
        except sqlite3.OperationalError as e:
            if "no such column: min_points" in str(e):
                print("Warning: rank_definitions table exists but has old schema. Run migrations to fix.")
                # Skip inserting for now - migrations will handle this
            else:
                raise e
        
        # Analytics tables
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity_log (
            log_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL,
            details TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            stat_date TEXT PRIMARY KEY,
            new_users INTEGER DEFAULT 0,
            total_confessions INTEGER DEFAULT 0,
            approved_confessions INTEGER DEFAULT 0,
            rejected_confessions INTEGER DEFAULT 0,
            total_comments INTEGER DEFAULT 0,
            active_users INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Add missing columns to posts table for analytics
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN status TEXT DEFAULT "pending"')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN sentiment_score REAL DEFAULT 0.0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN profanity_detected INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN spam_score REAL DEFAULT 0.0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Media support columns
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_type TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_file_id TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_file_unique_id TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_caption TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_file_size INTEGER')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_mime_type TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_duration INTEGER')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_width INTEGER')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_height INTEGER')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE posts ADD COLUMN media_thumbnail_file_id TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Update existing posts to have proper status
        cursor.execute('''
            UPDATE posts 
            SET status = CASE 
                WHEN approved = 1 THEN 'approved'
                WHEN approved = 0 THEN 'rejected'
                ELSE 'pending'
            END 
            WHERE status IS NULL OR status = 'pending'
        ''')
        
        conn.commit()

def add_user(user_id, username=None, first_name=None, last_name=None):
    """Add or update user information"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        
        if db_conn.use_postgresql:
            # PostgreSQL doesn't support INSERT OR REPLACE, use ON CONFLICT instead
            cursor.execute(f'''
                INSERT INTO users (user_id, username, first_name, last_name, join_date, questions_asked, comments_posted, blocked)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP, 0, 0, 0)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name
            ''', (user_id, username, first_name, last_name))
        else:
            cursor.execute(f'''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, join_date, questions_asked, comments_posted, blocked)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    COALESCE((SELECT join_date FROM users WHERE user_id = {placeholder} AND join_date IS NOT NULL), CURRENT_TIMESTAMP),
                    COALESCE((SELECT questions_asked FROM users WHERE user_id = {placeholder}), 0),
                    COALESCE((SELECT comments_posted FROM users WHERE user_id = {placeholder}), 0),
                    COALESCE((SELECT blocked FROM users WHERE user_id = {placeholder}), 0)
                )
            ''', (user_id, username, first_name, last_name, user_id, user_id, user_id, user_id))
        conn.commit()

def get_user_info(user_id):
    """Get complete user information"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f'''
            SELECT user_id, username, first_name, last_name, join_date, 
                   questions_asked, comments_posted, blocked
            FROM users WHERE user_id = {placeholder}
        ''', (user_id,))
        return cursor.fetchone()

def get_comment_count(post_id):
    """Get total comment count for a post (including replies)"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f'SELECT COUNT(*) FROM comments WHERE post_id = {placeholder}', (post_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

def is_blocked_user(user_id):
    """Check if user is blocked"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f'SELECT blocked FROM users WHERE user_id = {placeholder}', (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1

def get_user_posts(user_id, limit=10):
    """Get user's posts with status, comment count, and media information"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f'''
            SELECT p.post_id, p.content, p.category, p.timestamp, p.approved,
                   COUNT(c.comment_id) as comment_count, p.post_number,
                   p.media_type, p.media_file_id, p.media_file_unique_id, p.media_caption,
                   p.media_file_size, p.media_mime_type, p.media_duration, 
                   p.media_width, p.media_height, p.media_thumbnail_file_id
            FROM posts p
            LEFT JOIN comments c ON p.post_id = c.post_id
            WHERE p.user_id = {placeholder}
            GROUP BY p.post_id, p.content, p.category, p.timestamp, p.approved, p.post_number,
                     p.media_type, p.media_file_id, p.media_file_unique_id, p.media_caption,
                     p.media_file_size, p.media_mime_type, p.media_duration, 
                     p.media_width, p.media_height, p.media_thumbnail_file_id
            ORDER BY p.timestamp DESC
            LIMIT {placeholder}
        ''', (user_id, limit))
        return cursor.fetchall()
        
def get_post_author_id(post_id):
    """Get the user_id of the post author"""
    db_conn = get_db_connection()
    with db_conn.get_connection() as conn:
        cursor = conn.cursor()
        placeholder = db_conn.get_placeholder()
        cursor.execute(f'SELECT user_id FROM posts WHERE post_id = {placeholder}', (post_id,))
        result = cursor.fetchone()
        return result[0] if result else None
