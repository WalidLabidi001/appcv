"""
Database initialization and helper functions for the CV Manager application.
Uses SQLite with FTS5 for full-text search capabilities.
"""

import sqlite3
import json
import os

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')


def get_db():
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize the database schema and FTS index."""
    conn = get_db()
    cursor = conn.cursor()

    # Main CV table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cvs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT,
            file_type TEXT DEFAULT 'file',
            url TEXT,
            text TEXT,
            metadata_json TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # FTS5 virtual table for full-text search
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS cvs_fts USING fts5(
            text,
            metadata_json,
            content='cvs',
            content_rowid='id'
        )
    ''')

    # Triggers to keep FTS index in sync
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cvs_ai AFTER INSERT ON cvs BEGIN
            INSERT INTO cvs_fts(rowid, text, metadata_json)
            VALUES (new.id, new.text, new.metadata_json);
        END
    ''')

    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cvs_ad AFTER DELETE ON cvs BEGIN
            INSERT INTO cvs_fts(cvs_fts, rowid, text, metadata_json)
            VALUES ('delete', old.id, old.text, old.metadata_json);
        END
    ''')

    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cvs_au AFTER UPDATE ON cvs BEGIN
            INSERT INTO cvs_fts(cvs_fts, rowid, text, metadata_json)
            VALUES ('delete', old.id, old.text, old.metadata_json);
            INSERT INTO cvs_fts(rowid, text, metadata_json)
            VALUES (new.id, new.text, new.metadata_json);
        END
    ''')

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully.")


def check_duplicate(original_filename, text=None):
    """Check if a CV with same filename and context already exists."""
    conn = get_db()
    # If text is provided, we check for exact text match too
    if text and len(text) > 10:
        cv = conn.execute(
            'SELECT id FROM cvs WHERE original_filename = ? OR text = ? LIMIT 1',
            (original_filename, text)
        ).fetchone()
    else:
        cv = conn.execute(
            'SELECT id FROM cvs WHERE original_filename = ? LIMIT 1',
            (original_filename,)
        ).fetchone()
    conn.close()
    return cv['id'] if cv else None


def insert_cv(filename, original_filename, file_type, text, url=None, metadata=None):
    """Insert a new CV record into the database."""
    conn = get_db()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    cursor = conn.execute(
        '''INSERT INTO cvs (filename, original_filename, file_type, url, text, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (filename, original_filename, file_type, url, text, metadata_json)
    )
    cv_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return cv_id


def get_all_cvs(page=1, per_page=12, file_type=None):
    """Get all CVs with pagination and optional filtering by type."""
    conn = get_db()
    offset = (page - 1) * per_page

    query_params = []
    where_clause = ""
    
    if file_type in ['file', 'url']:
        where_clause = "WHERE file_type = ?"
        query_params.append(file_type)

    # Total count
    total_query = f'SELECT COUNT(*) FROM cvs {where_clause}'
    total = conn.execute(total_query, query_params).fetchone()[0]

    # Paginated results
    results_query = f'SELECT * FROM cvs {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?'
    cvs = conn.execute(results_query, query_params + [per_page, offset]).fetchall()

    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return cvs, total, total_pages


def get_cv_by_id(cv_id):
    """Get a single CV by its ID."""
    conn = get_db()
    cv = conn.execute('SELECT * FROM cvs WHERE id = ?', (cv_id,)).fetchone()
    conn.close()
    return cv


def search_cvs(query, page=1, per_page=12):
    """Search CVs using FTS5 full-text search."""
    conn = get_db()
    offset = (page - 1) * per_page

    # Sanitize query for FTS5
    search_terms = ' OR '.join([f'"{term}"' for term in query.split() if term.strip()])
    if not search_terms:
        conn.close()
        return [], 0, 0

    try:
        # Count matching results
        total = conn.execute(
            '''SELECT COUNT(*) FROM cvs WHERE id IN
               (SELECT rowid FROM cvs_fts WHERE cvs_fts MATCH ?)''',
            (search_terms,)
        ).fetchone()[0]

        # Get paginated results with highlighting
        cvs = conn.execute(
            '''SELECT cvs.*, snippet(cvs_fts, 0, '<mark>', '</mark>', '...', 40) as highlighted_text
               FROM cvs
               JOIN cvs_fts ON cvs.id = cvs_fts.rowid
               WHERE cvs_fts MATCH ?
               ORDER BY rank
               LIMIT ? OFFSET ?''',
            (search_terms, per_page, offset)
        ).fetchall()
    except Exception:
        # Fallback to LIKE search if FTS fails
        like_query = f'%{query}%'
        total = conn.execute(
            'SELECT COUNT(*) FROM cvs WHERE text LIKE ? OR metadata_json LIKE ?',
            (like_query, like_query)
        ).fetchone()[0]

        cvs = conn.execute(
            '''SELECT *, text as highlighted_text FROM cvs
               WHERE text LIKE ? OR metadata_json LIKE ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?''',
            (like_query, like_query, per_page, offset)
        ).fetchall()

    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return cvs, total, total_pages


def update_cv(cv_id, text, metadata):
    """Update a CV's text and metadata."""
    conn = get_db()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    conn.execute(
        'UPDATE cvs SET text = ?, metadata_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (text, metadata_json, cv_id)
    )
    conn.commit()
    conn.close()


def delete_cv(cv_id):
    """Delete a CV by its ID."""
    conn = get_db()
    conn.execute('DELETE FROM cvs WHERE id = ?', (cv_id,))
    conn.commit()
    conn.close()


def get_stats():
    """Get dashboard statistics."""
    conn = get_db()
    total_cvs = conn.execute('SELECT COUNT(*) FROM cvs').fetchone()[0]
    today_cvs = conn.execute(
        "SELECT COUNT(*) FROM cvs WHERE DATE(created_at) = DATE('now')"
    ).fetchone()[0]
    file_cvs = conn.execute(
        "SELECT COUNT(*) FROM cvs WHERE file_type = 'file'"
    ).fetchone()[0]
    url_cvs = conn.execute(
        "SELECT COUNT(*) FROM cvs WHERE file_type = 'url'"
    ).fetchone()[0]
    conn.close()
    return {
        'total': total_cvs,
        'today': today_cvs,
        'files': file_cvs,
        'urls': url_cvs
    }


if __name__ == '__main__':
    init_db()
