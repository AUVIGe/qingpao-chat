#!/usr/bin/env python3
"""Small-team private chat server; standard library only."""
import hashlib, json, mimetypes, os, secrets, sqlite3, time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
DATA = Path(os.environ.get("QINGPAO_DATA", "/opt/qingpao/data"))
DB = DATA / "qingpao.db"
UPLOADS = DATA / "uploads"
SESSION_AGE = 60 * 60 * 24 * 30
ONLINE_SECONDS = 75

def conn():
    DATA.mkdir(parents=True, exist_ok=True); UPLOADS.mkdir(exist_ok=True)
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    db = conn()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, password TEXT NOT NULL, created_at INTEGER NOT NULL, seen_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS pair_codes (code TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS friendships (user_a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, user_b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at INTEGER NOT NULL, PRIMARY KEY(user_a,user_b));
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, body TEXT NOT NULL DEFAULT '', attachment TEXT, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS call_signals (id INTEGER PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL);
    """)
    try: db.execute("ALTER TABLE messages ADD COLUMN burn_on_read INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError: pass
    db.commit(); db.close()

def password_hash(value, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, 210000)
    return salt.hex() + "$" + digest.hex()

def valid_password(value, stored):
    try:
        salt, _ = stored.split("$", 1)
        return secrets.compare_digest(password_hash(value, bytes.fromhex(salt)), stored)
    except ValueError: return False

class App(BaseHTTPRequestHandler):
    server_version = "Qingpao/1"
    def log_message(self, *_): pass
    def json(self, payload, status=200, cookie=None):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers(); self.wfile.write(raw)
    def error_json(self, message, status=400): self.json({"error":message}, status)
    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2 * 1024 * 1024: raise ValueError("内容过大")
        return json.loads(self.rfile.read(length) or b"{}")
    def user(self):
        token = SimpleCookie(self.headers.get("Cookie", "")).get("qp_session")
        if not token: return None
        db = conn(); row = db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?", (token.value, int(time.time()))).fetchone()
        if row: db.execute("UPDATE users SET seen_at=? WHERE id=?", (int(time.time()), row["id"])); db.commit()
        db.close(); return row
    def require(self):
        user = self.user()
        if not user: self.error_json("请先登录", HTTPStatus.UNAUTHORIZED)
        return user
    def static(self, path):
        file = PUBLIC / ("index.html" if path == "/" else path.lstrip("/"))
        if not file.is_file() or ".." in file.parts: self.send_error(404); return
        data = file.read_bytes(); typ = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", typ); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-cache"); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/me":
            u = self.user(); return self.json({"user": {"id":u["id"], "username":u["username"]} if u else None})
        if path == "/api/contacts": return self.contacts()
        if path == "/api/messages": return self.messages(parse_qs(urlparse(self.path).query))
        if path == "/api/call-signals": return self.call_signals(parse_qs(urlparse(self.path).query))
        if path.startswith("/uploads/"):
            file = UPLOADS / Path(path).name
            if not file.is_file(): return self.send_error(404)
            data=file.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(str(file))[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(data))); self.end_headers(); return self.wfile.write(data)
        self.static(path)
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/register": return self.register()
            if path == "/api/login": return self.login()
            if path == "/api/logout": return self.logout()
            if path == "/api/pair-code": return self.create_code()
            if path == "/api/pair": return self.pair()
            if path == "/api/messages": return self.send_message()
            if path == "/api/messages/read": return self.read_burn_message()
            if path == "/api/call-signals": return self.send_signal()
            return self.error_json("不存在的接口", 404)
        except (ValueError, KeyError, json.JSONDecodeError) as e: self.error_json(str(e) or "请求格式不正确")
    def register(self):
        p=self.body(); name=p.get("username","").strip(); password=p.get("password","")
        if not 2<=len(name)<=30 or not name.replace("_","").replace("-","").isalnum(): return self.error_json("用户名为 2–30 位字母、数字、下划线或连字符")
        if len(password)<8: return self.error_json("密码至少 8 位")
        db=conn(); now=int(time.time())
        try: cur=db.execute("INSERT INTO users(username,password,created_at,seen_at) VALUES(?,?,?,?)",(name,password_hash(password),now,now)); db.commit()
        except sqlite3.IntegrityError: db.close(); return self.error_json("用户名已被使用",409)
        token=secrets.token_urlsafe(32); db.execute("INSERT INTO sessions VALUES(?,?,?)",(token,cur.lastrowid,now+SESSION_AGE)); db.commit(); db.close()
        self.json({"user":{"id":cur.lastrowid,"username":name}},cookie=f"qp_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_AGE}; Secure")
    def login(self):
        p=self.body(); db=conn(); u=db.execute("SELECT * FROM users WHERE username=?",(p.get("username","").strip(),)).fetchone()
        if not u or not valid_password(p.get("password", ""),u["password"]): db.close(); return self.error_json("用户名或密码不正确",401)
        token=secrets.token_urlsafe(32); now=int(time.time()); db.execute("INSERT INTO sessions VALUES(?,?,?)",(token,u["id"],now+SESSION_AGE)); db.execute("UPDATE users SET seen_at=? WHERE id=?",(now,u["id"])); db.commit(); db.close()
        self.json({"user":{"id":u["id"],"username":u["username"]}},cookie=f"qp_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_AGE}; Secure")
    def logout(self):
        c=SimpleCookie(self.headers.get("Cookie", "")).get("qp_session")
        if c:
            db=conn(); db.execute("DELETE FROM sessions WHERE token=?",(c.value,)); db.commit(); db.close()
        self.json({"ok":True},cookie="qp_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax; Secure")
    def create_code(self):
        u=self.require()
        if not u:return
        code="-".join([secrets.token_hex(2).upper() for _ in range(3)]); db=conn(); db.execute("DELETE FROM pair_codes WHERE user_id=? OR expires_at<?",(u["id"],int(time.time()))); db.execute("INSERT INTO pair_codes VALUES(?,?,?)",(code,u["id"],int(time.time())+600)); db.commit(); db.close(); self.json({"code":code,"expires_in":600})
    def pair(self):
        u=self.require()
        if not u:return
        code=self.body().get("code","").strip().upper(); db=conn(); row=db.execute("SELECT user_id FROM pair_codes WHERE code=? AND expires_at>?",(code,int(time.time()))).fetchone()
        if not row or row["user_id"]==u["id"]: db.close(); return self.error_json("配对码无效或已过期")
        a,b=sorted((u["id"],row["user_id"])); db.execute("INSERT OR IGNORE INTO friendships VALUES(?,?,?)",(a,b,int(time.time()))); db.execute("DELETE FROM pair_codes WHERE code=?",(code,)); db.commit(); db.close(); self.json({"ok":True})
    def contacts(self):
        u=self.require()
        if not u:return
        db=conn(); rows=db.execute("SELECT u.id,u.username,u.seen_at FROM friendships f JOIN users u ON u.id=CASE WHEN f.user_a=? THEN f.user_b ELSE f.user_a END WHERE f.user_a=? OR f.user_b=? ORDER BY u.username",(u["id"],u["id"],u["id"])).fetchall(); db.close(); now=int(time.time())
        self.json({"contacts":[{"id":r["id"],"username":r["username"],"online":r["seen_at"]>now-ONLINE_SECONDS} for r in rows]})
    def messages(self, q):
        u=self.require()
        if not u:return
        other=int(q.get("with",[0])[0]); after=int(q.get("after",[0])[0]); db=conn(); ok=db.execute("SELECT 1 FROM friendships WHERE (user_a=? AND user_b=?) OR (user_a=? AND user_b=?)",(u["id"],other,other,u["id"])).fetchone()
        if not ok: db.close(); return self.error_json("不是好友",403)
        rows=db.execute("SELECT id,sender_id,body,attachment,created_at,burn_on_read FROM messages WHERE id>? AND ((sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)) ORDER BY id LIMIT 200",(after,u["id"],other,other,u["id"])).fetchall(); db.close(); self.json({"messages":[dict(r) for r in rows]})
    def send_message(self):
        u=self.require()
        if not u:return
        p=self.body(); other=int(p.get("to",0)); body=p.get("body","").strip()
        if not body or len(body)>4000:return self.error_json("消息长度应为 1–4000 字")
        db=conn(); ok=db.execute("SELECT 1 FROM friendships WHERE (user_a=? AND user_b=?) OR (user_a=? AND user_b=?)",(u["id"],other,other,u["id"])).fetchone()
        if not ok:db.close();return self.error_json("不是好友",403)
        cur=db.execute("INSERT INTO messages(sender_id,recipient_id,body,burn_on_read,created_at) VALUES(?,?,?,?,?)",(u["id"],other,body,1 if p.get("burn") else 0,int(time.time()))); db.commit(); db.close(); self.json({"id":cur.lastrowid})
    def read_burn_message(self):
        u=self.require()
        if not u:return
        msg_id=int(self.body().get("id",0)); db=conn(); db.execute("DELETE FROM messages WHERE id=? AND burn_on_read=1 AND (sender_id=? OR recipient_id=?)",(msg_id,u["id"],u["id"])); db.commit(); db.close(); self.json({"ok":True})
    def call_signals(self, q):
        u=self.require()
        if not u:return
        other=int(q.get("with",[0])[0]); after=int(q.get("after",[0])[0]); db=conn()
        rows=db.execute("SELECT id,sender_id,kind,payload FROM call_signals WHERE id>? AND sender_id=? AND recipient_id=? ORDER BY id LIMIT 200",(after,other,u["id"])).fetchall(); db.close()
        self.json({"signals":[dict(r) for r in rows]})
    def send_signal(self):
        u=self.require()
        if not u:return
        p=self.body(); other=int(p.get("to",0)); kind=p.get("kind",""); payload=p.get("payload")
        if kind not in ("offer","answer","ice","hangup") or payload is None:return self.error_json("无效的通话信令")
        db=conn(); ok=db.execute("SELECT 1 FROM friendships WHERE (user_a=? AND user_b=?) OR (user_a=? AND user_b=?)",(u["id"],other,other,u["id"])).fetchone()
        if not ok:db.close();return self.error_json("不是好友",403)
        db.execute("INSERT INTO call_signals(sender_id,recipient_id,kind,payload,created_at) VALUES(?,?,?,?,?)",(u["id"],other,kind,json.dumps(payload),int(time.time()))); db.commit(); db.close(); self.json({"ok":True})

if __name__ == "__main__":
    init_db(); port=int(os.environ.get("PORT","8120")); print(f"Qingpao listening on {port}"); ThreadingHTTPServer(("127.0.0.1",port),App).serve_forever()
