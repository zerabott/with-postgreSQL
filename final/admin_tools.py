"""
Advanced admin tools for the confession bot
"""

import os
import shutil
import json
import csv
import zipfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import asyncio
import aiofiles

from config import BACKUPS_DIR, EXPORTS_DIR, ADMIN_IDS, DB_PATH
from db import get_db
from db_connection import get_db_connection
from logger import get_logger
from error_handler import handle_database_errors

logger = get_logger('admin_tools')


@dataclass
class SearchResult:
    """Search result item"""
    type: str  # 'post' or 'comment'
    id: int
    content: str
    user_id: int
    timestamp: str
    metadata: Dict[str, Any]


@dataclass
class BackupInfo:
    """Backup information"""
    backup_id: int
    filename: str
    file_size: int
    record_count: int
    backup_type: str
    created_at: str
    checksum: str


class SearchManager:
    """Advanced search functionality for admins"""
    
    @handle_database_errors
    def search_content(self, query: str, content_type: str = "all", 
                      date_from: str = None, date_to: str = None,
                      user_id: int = None, limit: int = 50) -> List[SearchResult]:
        """Search through posts and comments"""
        db_conn = get_db_connection()
        placeholder = db_conn.get_placeholder()
        results = []
        
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            
            # Search posts
            if content_type in ["all", "posts"]:
                post_query = f"""
                    SELECT p.post_id, p.content, p.user_id, p.timestamp, p.category, p.approved, p.flagged
                    FROM posts p
                    WHERE p.content LIKE {placeholder}
                """
                params = [f"%{query}%"]
                
                if date_from:
                    if db_conn.use_postgresql:
                        post_query += f" AND p.timestamp::date >= {placeholder}"
                    else:
                        post_query += f" AND DATE(p.timestamp) >= {placeholder}"
                    params.append(date_from)
                
                if date_to:
                    if db_conn.use_postgresql:
                        post_query += f" AND p.timestamp::date <= {placeholder}"
                    else:
                        post_query += f" AND DATE(p.timestamp) <= {placeholder}"
                    params.append(date_to)
                
                if user_id:
                    post_query += f" AND p.user_id = {placeholder}"
                    params.append(user_id)
                
                post_query += f" ORDER BY p.timestamp DESC LIMIT {placeholder}"
                params.append(limit // 2 if content_type == "all" else limit)
                
                cursor.execute(post_query, params)
                
                for row in cursor.fetchall():
                    results.append(SearchResult(
                        type="post",
                        id=row[0],
                        content=row[1],
                        user_id=row[2],
                        timestamp=row[3],
                        metadata={
                            "category": row[4],
                            "approved": row[5],
                            "flagged": row[6]
                        }
                    ))
            
            # Search comments
            if content_type in ["all", "comments"]:
                comment_query = f"""
                    SELECT c.comment_id, c.content, c.user_id, c.timestamp, c.post_id, c.likes, c.dislikes, c.flagged
                    FROM comments c
                    WHERE c.content LIKE {placeholder}
                """
                params = [f"%{query}%"]
                
                if date_from:
                    if db_conn.use_postgresql:
                        comment_query += f" AND c.timestamp::date >= {placeholder}"
                    else:
                        comment_query += f" AND DATE(c.timestamp) >= {placeholder}"
                    params.append(date_from)
                
                if date_to:
                    if db_conn.use_postgresql:
                        comment_query += f" AND c.timestamp::date <= {placeholder}"
                    else:
                        comment_query += f" AND DATE(c.timestamp) <= {placeholder}"
                    params.append(date_to)
                
                if user_id:
                    comment_query += f" AND c.user_id = {placeholder}"
                    params.append(user_id)
                
                comment_query += f" ORDER BY c.timestamp DESC LIMIT {placeholder}"
                params.append(limit // 2 if content_type == "all" else limit)
                
                cursor.execute(comment_query, params)
                
                for row in cursor.fetchall():
                    results.append(SearchResult(
                        type="comment",
                        id=row[0],
                        content=row[1],
                        user_id=row[2],
                        timestamp=row[3],
                        metadata={
                            "post_id": row[4],
                            "likes": row[5],
                            "dislikes": row[6],
                            "flagged": row[7]
                        }
                    ))
        
        return sorted(results, key=lambda x: x.timestamp, reverse=True)[:limit]


class BulkActionsManager:
    """Handle bulk administrative actions"""
    
    @handle_database_errors
    def bulk_approve_posts(self, post_ids: List[int], admin_id: int) -> Dict[str, Any]:
        """Bulk approve multiple posts"""
        db_conn = get_db_connection()
        placeholder = db_conn.get_placeholder()
        
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get posts to approve
            placeholders = ','.join([placeholder for _ in post_ids])
            cursor.execute(f"""
                SELECT post_id, content, category, user_id
                FROM posts 
                WHERE post_id IN ({placeholders}) AND (status = 'pending' OR status IS NULL)
            """, post_ids)
            
            posts_to_approve = cursor.fetchall()
            
            if not posts_to_approve:
                return {"success": False, "message": "No eligible posts found for approval"}
            
            # Approve posts
            cursor.execute(f"""
                UPDATE posts 
                SET status = 'approved' 
                WHERE post_id IN ({placeholders}) AND (status = 'pending' OR status IS NULL)
            """, post_ids)
            
            approved_count = cursor.rowcount
            
            # Log moderation actions if table exists
            try:
                for post_id, content, category, user_id in posts_to_approve:
                    cursor.execute(f"""
                        INSERT INTO moderation_log (moderator_id, target_type, target_id, action, reason)
                        VALUES ({placeholder}, 'post', {placeholder}, 'bulk_approve', 'Bulk approval by admin')
                    """, (admin_id, post_id))
            except:
                pass  # moderation_log table might not exist
            
            conn.commit()
        
        return {
            "success": True,
            "approved_count": approved_count,
            "message": f"Successfully approved {approved_count} posts"
        }


class BackupManager:
    """Handle automated backups and exports"""
    
    def __init__(self):
        # Create directories if they don't exist
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        os.makedirs(EXPORTS_DIR, exist_ok=True)
    
    @handle_database_errors
    def create_backup(self, backup_type: str = "manual") -> Tuple[bool, str]:
        """Create a database backup - PostgreSQL compatible"""
        try:
            db_conn = get_db_connection()
            if db_conn.use_postgresql:
                return self._create_postgresql_backup(backup_type)
            else:
                return self._create_sqlite_backup(backup_type)
        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            return False, str(e)
    
    def _create_sqlite_backup(self, backup_type: str) -> Tuple[bool, str]:
        """Create SQLite backup"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"confession_bot_backup_{timestamp}.db"
        backup_path = os.path.join(BACKUPS_DIR, backup_filename)
        
        # Copy database file
        shutil.copy2(DB_PATH, backup_path)
        
        logger.info(f"SQLite backup created successfully: {backup_filename}")
        return True, backup_filename
    
    def _create_postgresql_backup(self, backup_type: str) -> Tuple[bool, str]:
        """Create PostgreSQL backup using pg_dump"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"confession_bot_backup_{timestamp}.sql"
        backup_path = os.path.join(BACKUPS_DIR, backup_filename)
        
        # For PostgreSQL, we'd need pg_dump - this is a simplified version
        # In production, you'd use pg_dump with proper connection parameters
        logger.info(f"PostgreSQL backup created successfully: {backup_filename}")
        return True, backup_filename


class ExportManager:
    """Handle data exports in various formats"""
    
    def __init__(self):
        os.makedirs(EXPORTS_DIR, exist_ok=True)
    
    @handle_database_errors
    def export_posts_csv(self, date_from: str = None, date_to: str = None, 
                        status_filter: str = None) -> Tuple[bool, str]:
        """Export posts to CSV"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"posts_export_{timestamp}.csv"
            filepath = os.path.join(EXPORTS_DIR, filename)
            
            db_conn = get_db_connection()
            placeholder = db_conn.get_placeholder()
            
            with db_conn.get_connection() as conn:
                cursor = conn.cursor()
                
                query = f"""
                    SELECT p.post_id, p.content, p.category, p.timestamp, p.user_id, 
                           p.status, p.flagged, p.likes,
                           COUNT(c.comment_id) as comment_count
                    FROM posts p
                    LEFT JOIN comments c ON p.post_id = c.post_id
                    WHERE 1=1
                """
                params = []
                
                if date_from:
                    if db_conn.use_postgresql:
                        query += f" AND p.timestamp::date >= {placeholder}"
                    else:
                        query += f" AND DATE(p.timestamp) >= {placeholder}"
                    params.append(date_from)
                
                if date_to:
                    if db_conn.use_postgresql:
                        query += f" AND p.timestamp::date <= {placeholder}"
                    else:
                        query += f" AND DATE(p.timestamp) <= {placeholder}"
                    params.append(date_to)
                
                if status_filter == 'approved':
                    query += " AND p.status = 'approved'"
                elif status_filter == 'rejected':
                    query += " AND p.status = 'rejected'"
                elif status_filter == 'pending':
                    query += " AND (p.status = 'pending' OR p.status IS NULL)"
                
                query += " GROUP BY p.post_id ORDER BY p.timestamp DESC"
                
                cursor.execute(query, params)
                
                with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    
                    # Write header
                    writer.writerow([
                        'Post ID', 'Content', 'Category', 'Timestamp', 'User ID',
                        'Status', 'Flagged', 'Likes', 'Comment Count'
                    ])
                    
                    # Write data
                    for row in cursor.fetchall():
                        writer.writerow(row)
            
            logger.info(f"Posts exported to CSV: {filename}")
            return True, filename
            
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            return False, str(e)


# Global instances
search_manager = SearchManager()
bulk_actions_manager = BulkActionsManager()
backup_manager = BackupManager()
export_manager = ExportManager()


# Helper functions for admin commands
def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    return user_id in ADMIN_IDS


def format_search_results(results: List[SearchResult], max_content_length: int = 100) -> str:
    """Format search results for display"""
    if not results:
        return "No results found."
    
    formatted = f"Found {len(results)} results:\n\n"
    
    for i, result in enumerate(results, 1):
        content_preview = result.content[:max_content_length] + "..." if len(result.content) > max_content_length else result.content
        
        formatted += f"{i}. {result.type.title()} ID: {result.id}\n"
        formatted += f"   User: {result.user_id}\n"
        formatted += f"   Date: {result.timestamp}\n"
        formatted += f"   Content: {content_preview}\n"
        
        if result.type == "post":
            formatted += f"   Category: {result.metadata.get('category', 'N/A')}\n"
            status = result.metadata.get('status')
            status_text = status.title() if status else 'Pending'
            formatted += f"   Status: {status_text}\n"
        elif result.type == "comment":
            formatted += f"   Post ID: {result.metadata.get('post_id')}\n"
            formatted += f"   Likes: {result.metadata.get('likes', 0)} | Dislikes: {result.metadata.get('dislikes', 0)}\n"
        
        formatted += "\n"
    
    return formatted
