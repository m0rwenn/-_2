
# app.py — учебный сервис заметок (Modern UI)
# ВНИМАНИЕ: намеренно содержит уязвимости (OWASP Top 10).
# Запускать строго локально (127.0.0.1) или в изолированной ВМ.

import html
import http.server
import secrets
import sqlite3
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8000
DB_FILE = "notes.db"

# Сессии в памяти: token -> (user_id, username)
SESSIONS = {}


# ==========================================
# 1. БАЗА ДАННЫХ
# ==========================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS notes;

        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );

        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        INSERT INTO users (username, password) VALUES
            ('alice', 'alice123'),
            ('bob', 'bob456'),
            ('admin', 'SuperSecretAdminPass!');

        INSERT INTO notes (user_id, title, content) VALUES
            (1, '🛒 Список покупок', 'Овсяное молоко, зерновой кофе, манго'),
            (2, '🔒 Личный дневник Боба', 'Секретный пароль от корпоративного Wi-Fi: 99887766'),
            (3, '🚨 СЕКРЕТНЫЙ КЛЮЧ АДМИНИСТРАТОРА', 'FLAG{idor_and_sqli_are_dangerous}');
    """)
    conn.commit()
    conn.close()


# ==========================================
# 2. КРАСИВЫЙ ШАБЛОН (CSS)
# ==========================================

def render_page(title, body, user=None):
    if user:
        user_badge = f'<span class="badge">👤 {html.escape(user[1])}</span>'
        nav_links = f"""
            <a href="/" class="nav-link">📝 Мои заметки</a>
            <a href="/new" class="nav-link highlight">+ Новая заметка</a>
            <a href="/search" class="nav-link">🔍 Поиск</a>
            <a href="/logout" class="nav-link danger">Выйти</a>
        """
    else:
        user_badge = ''
        nav_links = """
            <a href="/" class="nav-link">Главная</a>
            <a href="/login" class="nav-link">Войти</a>
            <a href="/register" class="nav-link highlight">Регистрация</a>
        """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — CloudNotes</title>
    <style>
        :root {{
            --bg: #f8fafc;
            --surface: #ffffff;
            --primary: #4f46e5;
            --primary-hover: #4338ca;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --danger: #ef4444;
            --radius: 12px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            line-height: 1.6;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        header {{
            background: var(--surface);
            padding: 16px 24px;
            border-radius: var(--radius);
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -2px rgba(0,0,0,0.05);
            border: 1px solid var(--border);
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .logo {{ font-weight: 800; font-size: 1.25rem; color: var(--primary); text-decoration: none; }}
        nav {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .nav-link {{
            text-decoration: none;
            color: var(--text-muted);
            font-weight: 500;
            font-size: 0.9rem;
            padding: 6px 12px;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .nav-link:hover {{ background: #f1f5f9; color: var(--text-main); }}
        .nav-link.highlight {{ background: var(--primary); color: white; }}
        .nav-link.highlight:hover {{ background: var(--primary-hover); }}
        .nav-link.danger:hover {{ background: #fee2e2; color: var(--danger); }}
        .badge {{ background: #e0e7ff; color: var(--primary); font-size: 0.85rem; font-weight: 600; padding: 4px 10px; border-radius: 20px; }}
        
        .card {{
            background: var(--surface);
            padding: 24px;
            border-radius: var(--radius);
            border: 1px solid var(--border);
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
            margin-bottom: 16px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.07);
        }}
        .card h3 a {{ color: var(--text-main); text-decoration: none; font-size: 1.2rem; }}
        .card h3 a:hover {{ color: var(--primary); }}
        .card p {{ color: var(--text-muted); margin-top: 8px; }}
        
        .input-group {{ margin-bottom: 16px; }}
        label {{ display: block; font-size: 0.85rem; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; }}
        input, textarea {{
            width: 100%;
            padding: 12px 14px;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 0.95rem;
            font-family: inherit;
            transition: border-color 0.2s, box-shadow 0.2s;
            outline: none;
        }}
        input:focus, textarea:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.15);
        }}
        button {{
            background: var(--primary);
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: background 0.2s;
            width: 100%;
        }}
        button:hover {{ background: var(--primary-hover); }}
        .error-box {{ background: #fef2f2; border-left: 4px solid var(--danger); padding: 12px; color: var(--danger); border-radius: 4px; margin-bottom: 16px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <a href="/" class="logo">✦ CloudNotes</a>
            <nav>
                {user_badge}
                {nav_links}
            </nav>
        </header>
        <main>
            {body}
        </main>
    </div>
</body>
</html>"""


# ==========================================
# 3. ЛОГИКА СТРАНИЦ
# ==========================================

def view_index(user):
    if not user:
        return render_page("Главная", """
            <div class="card" style="text-align: center; padding: 48px 20px;">
                <h1 style="font-size: 2.2rem; margin-bottom: 12px;">Умные личные заметки</h1>
                <p style="margin-bottom: 24px; color: var(--text-muted);">Безопасное облачное хранилище для ваших мыслей и секретов.</p>
                <div style="display: flex; gap: 12px; justify-content: center; max-width: 300px; margin: 0 auto;">
                    <a href="/login" class="nav-link" style="flex: 1; text-align: center; border: 1px solid var(--border);">Войти</a>
                    <a href="/register" class="nav-link highlight" style="flex: 1; text-align: center;">Регистрация</a>
                </div>
            </div>
        """)

    conn = get_db()
    notes = conn.execute(
        "SELECT id, title, content FROM notes WHERE user_id = ?", (user[0],)
    ).fetchall()
    conn.close()

    items = ""
    for n in notes:
        # УЯЗВИМОСТЬ: Stored XSS (вывод заголовка и контента без экранирования)
        items += f"""
        <div class="card">
            <h3><a href="/note?id={n['id']}">{n['title']}</a></h3>
            <p>{n['content']}</p>
        </div>
        """
    body = f"<h2 style='margin-bottom: 20px;'>Ваши заметки</h2>" + (items or "<p style='color: var(--text-muted);'>Здесь пока ничего нет. Создайте первую заметку!</p>")
    return render_page("Мои заметки", body, user)


def view_note_detail(user, note_id):
    conn = get_db()
    # УЯЗВИМОСТЬ: IDOR (нет проверки владельца user_id)
    note = conn.execute("SELECT id, user_id, title, content FROM notes WHERE id = ?", (note_id,)).fetchone()
    conn.close()

    if not note:
        return 404, render_page("Не найдено", "<div class='error-box'>Заметка не найдена</div>", user)

    # УЯЗВИМОСТЬ: Stored XSS
    body = f"""
        <div class="card">
            <span class="badge" style="margin-bottom: 12px; display: inline-block;">Заметка #{note['id']} • Владелец ID: {note['user_id']}</span>
            <h1 style="margin-bottom: 16px;">{note['title']}</h1>
            <p style="font-size: 1.1rem; line-height: 1.7; color: var(--text-main);">{note['content']}</p>
            <div style="margin-top: 24px; border-top: 1px solid var(--border); padding-top: 16px;">
                <a href="/" style="color: var(--primary); text-decoration: none; font-weight: 600;">← Назад к списку</a>
            </div>
        </div>
    """
    return 200, render_page(f"Заметка #{note['id']}", body, user)


def view_search(user, query):
    results_html = ""
    if query:
        conn = get_db()
        try:
            # УЯЗВИМОСТЬ: SQL Injection через f-строку
            sql = f"SELECT id, title, content FROM notes WHERE title LIKE '%{query}%'"
            rows = conn.execute(sql).fetchall()
            for r in rows:
                results_html += f"""
                    <div class="card">
                        <h3><a href='/note?id={r['id']}'>{html.escape(r['title'])}</a></h3>
                        <p>{html.escape(r['content'])}</p>
                    </div>
                """
        except sqlite3.Error as e:
            # УЯЗВИМОСТЬ: Утечка деталей ошибки SQL
            results_html = f"<div class='error-box'><b>Ошибка SQL:</b> {html.escape(str(e))}</div>"
        finally:
            conn.close()

    body = f"""
        <div class="card" style="margin-bottom: 24px;">
            <h2 style="margin-bottom: 16px;">Поиск по базе заметок</h2>
            <form method="GET" action="/search">
                <div class="input-group">
                    <input name="q" placeholder="Введите название заметки..." value="{html.escape(query)}">
                </div>
                <button type="submit">Найти</button>
            </form>
        </div>
        <h3 style="margin-bottom: 16px; color: var(--text-muted);">Результаты поиска:</h3>
        {results_html or '<p style="color: var(--text-muted);">По запросу ничего не найдено</p>'}
    """
    return render_page("Поиск", body, user)


# ==========================================
# 4. HTTP-СЕРВЕР
# ==========================================

class NotesHandler(http.server.BaseHTTPRequestHandler):
    def _send_html(self, status, content, headers=()):
        body_bytes = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body_bytes)

    def _redirect(self, url, headers=()):
        self.send_response(303)
        self.send_header("Location", url)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()

    def _get_current_user(self):
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        morsel = cookie.get("session")
        if morsel and morsel.value in SESSIONS:
            return SESSIONS[morsel.value]
        return None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        user = self._get_current_user()

        if parsed.path == "/":
            self._send_html(200, view_index(user))

        elif parsed.path == "/login":
            body = """
                <div class="card" style="max-width: 400px; margin: 40px auto;">
                    <h2 style="margin-bottom: 20px;">Вход</h2>
                    <form method="POST" action="/login">
                        <div class="input-group">
                            <label>Логин</label>
                            <input name="username" required>
                        </div>
                        <div class="input-group">
                            <label>Пароль</label>
                            <input name="password" type="password" required>
                        </div>
                        <button type="submit">Войти</button>
                    </form>
                </div>
            """
            self._send_html(200, render_page("Вход", body, user))

        elif parsed.path == "/register":
            body = """
                <div class="card" style="max-width: 400px; margin: 40px auto;">
                    <h2 style="margin-bottom: 20px;">Регистрация</h2>
                    <form method="POST" action="/register">
                        <div class="input-group">
                            <label>Логин</label>
                            <input name="username" required>
                        </div>
                        <div class="input-group">
                            <label>Пароль</label>
                            <input name="password" type="password" required>
                        </div>
                        <button type="submit">Создать аккаунт</button>
                    </form>
                </div>
            """
            self._send_html(200, render_page("Регистрация", body, user))

        elif parsed.path == "/logout":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie.get("session")
            if token and token.value in SESSIONS:
                del SESSIONS[token.value]
            self._redirect("/", [("Set-Cookie", "session=; Path=/; Max-Age=0")])

        elif parsed.path == "/new":
            if not user:
                return self._redirect("/login")
            body = """
                <div class="card">
                    <h2 style="margin-bottom: 20px;">Создать новую заметку</h2>
                    <form method="POST" action="/new">
                        <div class="input-group">
                            <label>Заголовок заметки</label>
                            <input name="title" placeholder="Например: План на выходные" required>
                        </div>
                        <div class="input-group">
                            <label>Текст заметки</label>
                            <textarea name="content" rows="6" placeholder="Напишите текст..." required></textarea>
                        </div>
                        <button type="submit">Сохранить заметку</button>
                    </form>
                </div>
            """
            self._send_html(200, render_page("Новая заметка", body, user))

        elif parsed.path == "/note":
            note_id = params.get("id", [""])[0]
            if not note_id.isdigit():
                return self._send_html(400, render_page("Ошибка", "<div class='error-box'>Некорректный ID</div>", user))
            status, page_html = view_note_detail(user, int(note_id))
            self._send_html(status, page_html)

        elif parsed.path == "/search":
            q = params.get("q", [""])[0]
            self._send_html(200, view_search(user, q))

        else:
            self._send_html(404, render_page("404", "<div class='error-box'>Страница не найдена</div>", user))

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        user = self._get_current_user()

        if parsed.path == "/login":
            username = form.get("username", [""])[0]
            password = form.get("password", [""])[0]

            conn = get_db()
            row = conn.execute(
                "SELECT id, username FROM users WHERE username = ? AND password = ?",
                (username, password)
            ).fetchone()
            conn.close()

            if row:
                token = secrets.token_hex(16)
                SESSIONS[token] = (row["id"], row["username"])
                self._redirect("/", [("Set-Cookie", f"session={token}; Path=/; HttpOnly")])
            else:
                body = "<div class='card' style='max-width: 400px; margin: 40px auto;'><div class='error-box'>Неверный логин или пароль</div><a href='/login' style='color: var(--primary);'>Попробовать снова</a></div>"
                self._send_html(401, render_page("Ошибка", body))

        elif parsed.path == "/register":
            username = form.get("username", [""])[0].strip()
            password = form.get("password", [""])[0].strip()

            if not username or not password:
                return self._send_html(400, render_page("Ошибка", "<div class='error-box'>Заполните все поля</div>"))

            conn = get_db()
            try:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                self._redirect("/login")
            except sqlite3.IntegrityError:
                self._send_html(400, render_page("Ошибка", "<div class='error-box'>Логин уже занят!</div>"))
            finally:
                conn.close()

        elif parsed.path == "/new":
            if not user:
                return self._redirect("/login")
            title = form.get("title", [""])[0]
            content = form.get("content", [""])[0]

            conn = get_db()
            conn.execute(
                "INSERT INTO notes (user_id, title, content) VALUES (?, ?, ?)",
                (user[0], title, content)
            )
            conn.commit()
            conn.close()
            self._redirect("/")


if __name__ == "__main__":
    init_db()
    server = http.server.ThreadingHTTPServer((HOST, PORT), NotesHandler)
    print(f"[*] Сервер запущен: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
