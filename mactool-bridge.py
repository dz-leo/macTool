#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mac 工具管理台 · 本地 bridge
────────────────────────────────────────────────────────────
只用 Python 标准库，零第三方依赖。
职责：
  1. 托管工作台页面（同源，无 CORS / 混合内容问题）
  2. 提供白名单本机能力（服务状态、启停、开终端、打开配置等）

安全边界（重要，请勿放宽）：
  · 只监听 127.0.0.1，外网和局域网都访问不到
  · 只开放白名单动作，绝不提供「执行任意命令」接口
  · 所有路径参数做绝对路径校验，拒绝 .. 穿越与空值
  · 新建文件只允许在已存在目录内创建单个常规文件

用法：
  python3 mactool-bridge.py            # 默认 8899，占用则自动顺延
  python3 mactool-bridge.py 9000       # 指定端口
"""

import errno
import http.server
import json
import os
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import sys
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGE_FILE = os.path.join(BASE_DIR, "mactool-workspace.html")


def _identity():
    """可靠地取当前用户与家目录。

    关键点：以 launchd / 任务调度等方式启动时，进程的 USER / HOME
    环境变量常常是空的，brew 会因此罢工。这里用 pwd 兜底并回写环境，
    保证子进程（brew / open 等）拿到正确的 HOME。
    """
    try:
        pw = pwd.getpwuid(os.getuid())
        user, home = pw.pw_name, pw.pw_dir
    except Exception:
        user = os.environ.get("USER") or ""
        home = os.environ.get("HOME") or os.path.expanduser("~")
    if not os.environ.get("HOME"):
        os.environ["HOME"] = home
    if not os.environ.get("USER"):
        os.environ["USER"] = user
    # launchd 拉起时 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，找不到 brew。
    # 把 Homebrew 常见安装位置补进去，保证 sh() 能执行 brew。
    extra_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
    path = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in path.split(":"):
            path = path + ":" + p if path else p
    os.environ["PATH"] = path
    return user, home


CUR_USER, CUR_HOME = _identity()

ALLOWED_SERVICE_ACT = {"start", "stop", "restart", "kill"}

# 终端优先级：装在前面的优先；Terminal.app 兜底（走 LaunchServices，零授权）
TERMINALS = [
    ("iTerm", "/Applications/iTerm.app"),
    ("Warp", "/Applications/Warp.app"),
    ("Ghostty", "/Applications/Ghostty.app"),
    ("Alacritty", "/Applications/Alacritty.app"),
    ("kitty", "/Applications/kitty.app"),
    ("WezTerm", "/Applications/WezTerm.app"),
    ("Terminal", "/System/Applications/Utilities/Terminal.app"),
]

# 编辑器优先级
EDITORS = [
    ("Visual Studio Code", "/Applications/Visual Studio Code.app", "code"),
    ("Sublime Text", "/Applications/Sublime Text.app", "subl"),
    ("Cursor", "/Applications/Cursor.app", "cursor"),
    ("Zed", "/Applications/Zed.app", "zed"),
    ("Nova", "/Applications/Nova.app", "nova"),
]

# 服务名关键词 -> 进程名前缀（lsof 会把长名字截断）
CMD_MAP = {
    "nginx": "nginx",
    "mysql": "mysqld",
    "mariadb": "mysqld",
    "redis": "redis",
    "php": "php",
    "postgresql": "postgres",
    "mongodb": "mongod",
    "memcached": "memcach",
    "rabbitmq": "beam",
    "elasticsearch": "java",
    "dnsmasq": "dnsmasq",
    "caddy": "caddy",
    "grafana": "grafana",
    "prometheus": "prometheus",
}

SAFE_NAME_RE = re.compile(r"^[^/\x00]{1,120}$")


# ─────────────────────────────── 基础工具 ───────────────────────────────

def sh(cmd, timeout=30):
    """执行白名单命令，统一返回结构。绝不接受外部传入的任意命令字符串。"""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "out": p.stdout.strip(), "err": p.stderr.strip(), "code": p.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "", "err": "命令执行超时", "code": -1}
    except Exception as e:
        return {"ok": False, "out": "", "err": str(e), "code": -1}


def safe_path(p):
    """校验路径：必须是已存在的绝对路径，且不含 .. 穿越。"""
    if not p or not isinstance(p, str):
        return None
    p = p.strip()
    if not p.startswith("/"):
        return None
    if ".." in p.split("/"):
        return None
    if not os.path.exists(p):
        return None
    return p


def safe_dir(p):
    d = safe_path(p)
    return d if d and os.path.isdir(d) else None


def listening_ports():
    """读取本机 TCP 监听端口。"""
    r = sh("lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null")
    rows = []
    for line in r["out"].splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        cmd, pid, addr = parts[0], parts[1], parts[8]
        m = re.search(r":(\d+)$", addr)
        if not m:
            continue
        port = int(m.group(1))
        if any(x["cmd"] == cmd and x["port"] == port for x in rows):
            continue
        rows.append({"cmd": cmd, "pid": pid, "port": port, "addr": addr})
    rows.sort(key=lambda x: x["port"])
    return rows


def service_key(name):
    """从 brew 服务名提取关键词，用于匹配进程。mysql@8.0 -> mysql"""
    return re.sub(r"@.*$", "", name.split("/")[-1])


def match_ports(name, ports):
    """把服务名关联到它占用的端口。"""
    key = service_key(name)
    proc = CMD_MAP.get(key)
    if not proc:
        for k, v in CMD_MAP.items():
            if key.startswith(k) or k.startswith(key):
                proc = v
                break
    if not proc:
        proc = key[:8]
    n = min(len(proc), 8)
    return [p["port"] for p in ports if p["cmd"][:n].lower() == proc[:n].lower()]


def port_alive(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, int(port)), timeout=0.6):
            return True
    except Exception:
        return False


def installed_app(path):
    return os.path.isdir(path)


def pick_terminal():
    for name, path in TERMINALS:
        if installed_app(path):
            return name
    return "Terminal"


def local_probe(ports):
    return {str(p): port_alive(p) for p in ports}


# ─────────────────────────────── 业务 API ───────────────────────────────

def api_ping(q):
    return {
        "ok": True,
        "host": os.uname().nodename,
        "user": CUR_USER,
        "home": CUR_HOME,
        "macos": sh("sw_vers -productVersion")["out"],
        "terminal": pick_terminal(),
        "editor": pick_editor(),
        "brew": brew_prefix(),
    }


def pick_editor():
    for name, path, cli in EDITORS:
        if installed_app(path):
            return name
    return ""


def api_services(q):
    r = sh("brew services list --json", timeout=40)
    try:
        data = json.loads(r["out"]) if r["out"] else []
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []
    ports = listening_ports()
    for s in data:
        s["ports"] = match_ports(s.get("name", ""), ports)
        s["running"] = s.get("status") == "started"
        s["conf"] = guess_conf(s.get("name", ""))
    data.sort(key=lambda x: (not x.get("running"), x.get("name", "")))
    return {"ok": True, "services": data, "ports": ports, "terminal": pick_terminal()}


_BREW_PREFIX = None


def brew_prefix():
    """brew --prefix 结果缓存，避免每个服务都起一次子进程。"""
    global _BREW_PREFIX
    if _BREW_PREFIX is None:
        _BREW_PREFIX = sh("brew --prefix")["out"] or "/opt/homebrew"
    return _BREW_PREFIX


def guess_conf(name):
    """猜测服务的配置文件路径（用于「一键直达」）。

    各个包的配置文件命名并不统一（mysql 用 my.cnf、nginx 用 nginx.conf），
    所以这里对已知的特例做别名兜底。
    """
    brew = brew_prefix()
    key = service_key(name)
    keys = [key]
    if key in ("mysql", "mariadb"):
        keys.append("my")
    if key.startswith("postgres"):
        keys += ["postgresql", "pgsql"]
    cands = []
    for k in keys:
        cands += [
            f"{brew}/etc/{k}/{k}.conf",
            f"{brew}/etc/{k}.conf",
            f"{brew}/etc/{k}/{k}.cnf",
            f"{brew}/etc/{k}.cnf",
            f"{brew}/etc/{k}/{k}.ini",
            f"{brew}/etc/{k}.ini",
            f"{brew}/etc/{k}/{k}.yml",
            f"{brew}/etc/{k}.yml",
        ]
    cands.append(f"{brew}/etc/{key}/nginx.conf")
    for c in cands:
        if os.path.isfile(c):
            return c
    # php 的 ini 层级特殊
    m = re.match(r"^php@?([\d.]+)?$", name.split("/")[-1])
    if m:
        ver = m.group(1)
        if ver:
            p = f"{brew}/etc/php/{ver}/php.ini"
            if os.path.isfile(p):
                return p
        try:
            vs = [d for d in os.listdir(f"{brew}/etc/php") if re.match(r"^[\d.]+$", d)]
            if vs:
                vs.sort()
                p = f"{brew}/etc/php/{vs[-1]}/php.ini"
                if os.path.isfile(p):
                    return p
        except Exception:
            pass
    return ""


def api_service_act(q):
    name = (q.get("name") or [""])[0].strip()
    act = (q.get("act") or [""])[0].strip()
    if act not in ALLOWED_SERVICE_ACT:
        return {"ok": False, "err": "不支持的动作"}, 400
    if not name or not re.match(r"^[\w@.\-+/]+$", name):
        return {"ok": False, "err": "服务名不合法"}, 400
    # 服务名作为独立参数传递并转义，杜绝注入
    r = sh(f"brew services {act} {shlex.quote(name)}", timeout=60)
    return {"ok": r["ok"], "out": r["out"], "err": r["err"]}


def api_ports(q):
    return {"ok": True, "ports": listening_ports()}


def api_outdated(q):
    r = sh("brew outdated --formula", timeout=90)
    names = [x for x in r["out"].splitlines() if x.strip()]
    return {"ok": True, "outdated": names}


def api_open(q):
    p = safe_path((q.get("path") or [""])[0])
    if not p:
        return {"ok": False, "err": "路径不存在或不合法"}, 400
    return sh(f"open {shlex.quote(p)}")


def api_reveal(q):
    p = safe_path((q.get("path") or [""])[0])
    if not p:
        return {"ok": False, "err": "路径不存在或不合法"}, 400
    return sh(f"open -R {shlex.quote(p)}")


def api_terminal(q):
    d = safe_dir((q.get("path") or [""])[0])
    if not d:
        return {"ok": False, "err": "目录不存在或不合法"}, 400
    app = pick_terminal()
    # open -a 走 LaunchServices，不需要「自动化」授权（osascript 需要，实测会 -10004）
    return sh(f"open -a {shlex.quote(app)} {shlex.quote(d)}")


def api_editor(q):
    p = safe_path((q.get("path") or [""])[0])
    if not p:
        return {"ok": False, "err": "路径不存在或不合法"}, 400
    for name, path, cli in EDITORS:
        if installed_app(path):
            if sh(f"command -v {cli}")["ok"]:
                return sh(f"{cli} {shlex.quote(p)}")
            return sh(f"open -a {shlex.quote(name)} {shlex.quote(p)}")
    return sh(f"open {shlex.quote(p)}")


def api_newfile(q):
    """在指定目录内新建单个常规文件。文件名不含路径分隔符，杜绝穿越。"""
    d = safe_dir((q.get("dir") or [""])[0])
    if not d:
        return {"ok": False, "err": "目录不存在或不合法"}, 400
    name = (q.get("name") or [""])[0].strip()
    if not name or not SAFE_NAME_RE.match(name):
        return {"ok": False, "err": "文件名不合法（不能包含 / 且不超过 120 字符）"}, 400
    if name in (".", ".."):
        return {"ok": False, "err": "文件名不合法"}, 400
    target = os.path.join(d, name)
    if os.path.exists(target):
        return {"ok": False, "err": "该目录下已存在同名文件"}, 400
    try:
        open(target, "a").close()
        return {"ok": True, "path": target}
    except Exception as e:
        return {"ok": False, "err": str(e)}, 500


def api_health(q):
    raw = (q.get("ports") or [""])[0]
    nums = []
    for x in re.split(r"[,\s]+", raw):
        if x.isdigit():
            n = int(x)
            if 0 < n < 65536:
                nums.append(n)
    nums = sorted(set(nums))[:40]
    return {"ok": True, "result": local_probe(nums)}


def api_kill(q):
    """结束进程。安全约束：PID 必须是数字，且必须在当前 LISTEN 列表中（防止误杀无关进程）。"""
    pid = (q.get("pid") or [""])[0].strip()
    if not pid.isdigit():
        return {"ok": False, "err": "PID 不合法"}, 400
    pid = int(pid)
    if pid <= 1 or pid == os.getpid():
        return {"ok": False, "err": "拒绝操作该进程"}, 400
    allowed = {int(p["pid"]) for p in listening_ports() if p["pid"].isdigit()}
    if pid not in allowed:
        return {"ok": False, "err": "只能结束当前处于监听状态的进程"}, 403
    r = sh(f"kill -9 {pid}")
    return {"ok": r["ok"], "err": r["err"] if not r["ok"] else ""}


def api_disk(q):
    r = sh("df -h / | tail -1")
    parts = r["out"].split()
    mem = sh("vm_stat | head -8")
    return {"ok": True,
            "disk": {"total": parts[1] if len(parts) > 1 else "-",
                     "used": parts[2] if len(parts) > 2 else "-",
                     "avail": parts[3] if len(parts) > 3 else "-",
                     "pct": parts[4] if len(parts) > 4 else "-"},
            "vmstat": mem["out"]}


# ─────────────────────────────── 磁盘清理 ───────────────────────────────
# 原则：目标路径全部硬编码在此白名单里，客户端只能传 key，永远传不进路径。
# 只清缓存类目录的「内容」，目录壳保留；个人文档目录一律不碰。

CLEAN_TARGETS = [
    # key,             显示名,             路径(支持 ~),            risk, 说明
    ("trash",          "废纸篓",            "~/.Trash",                     1, "已删除文件的残留，清空后不可恢复"),
    ("dsstore",        ".DS_Store 文件",    None,                           1, "Finder 自动生成的视图配置文件，删除无任何影响"),
    ("user_cache",     "用户应用缓存",      "~/Library/Caches",             2, "各类应用缓存，清理后应用首次启动会重新生成"),
    ("logs",           "用户日志",          "~/Library/Logs",               2, "应用日志，排查问题时才有用"),
    ("npm_cache",      "npm 缓存",          "~/.npm/_cacache",              2, "npm 下载缓存，下次 install 变慢"),
    ("yarn_cache",     "Yarn 缓存",         "~/Library/Caches/Yarn",        2, ""),
    ("gradle_cache",   "Gradle 构建缓存",   "~/.gradle/caches",             3, "Java/Android 构建缓存，下次构建会重新下载"),
    ("derived_data",   "Xcode 编译产物",    "~/Library/Developer/Xcode/DerivedData",   3, "下次编译全部重建，编译时间明显变长"),
    ("sim_cache",      "模拟器缓存",        "~/Library/Developer/CoreSimulator/Caches", 3, "iOS 模拟器临时数据"),
    ("ios_backup",     "iOS 设备备份",      "~/Library/Application Support/MobileSync/Backup", 3,
     "可能包含微信聊天记录等，删除后 iPhone 恢复会丢数据。没有 iCloud/电脑备份千万别删！"),
]

# .DS_Store 只扫这些目录（限深 4 层，跳过 Library），不做全盘扫描
DSSTORE_ROOTS = ["~/Desktop", "~/Documents", "~/Downloads", "~/Sites"]

DSSTORE_KEY = "dsstore"


def _du_size(path, timeout=90):
    """du -k 统计目录/文件大小（字节）。失败返回 0。"""
    if not path:
        return 0
    try:
        p = subprocess.run(["du", "-sk", "-x", path], capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0 and p.stdout.strip():
            return int(p.stdout.split()[0]) * 1024
    except Exception:
        pass
    return 0


def dsstore_files():
    """收集常见个人目录下的 .DS_Store 文件。"""
    out = []
    for r in DSSTORE_ROOTS:
        root = os.path.expanduser(r)
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("/").count("/")
        for dirpath, dirs, files in os.walk(root):
            if dirpath.rstrip("/").count("/") - base_depth >= 4:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in ("Library", "node_modules", ".git")]
            out += [os.path.join(dirpath, f) for f in files if f == ".DS_Store"]
    return out


_ERRNO_ZH = {
    "EACCES": "没有权限（目录归属其他用户或受系统保护）",
    "EPERM": "系统不允许此操作（可能受 SIP 保护）",
    "EBUSY": "文件正被其他程序占用",
    "ETXTBSY": "文件正在被执行",
    "ENOENT": "条目已不存在（可能刚被其他程序清理）",
    "ENOTEMPTY": "目录非空且无法递归删除",
    "EIO": "磁盘读写错误",
    "EROFS": "只读文件系统，不可删除",
}


def _clean_entry(p):
    """删除单个条目。返回 (是否成功, 失败原因中文描述)。"""
    try:
        if os.path.islink(p) or os.path.isfile(p):
            os.remove(p)
        elif os.path.isdir(p):
            shutil.rmtree(p)
        else:
            return False, "非常规文件类型，已跳过"
        return True, ""
    except Exception as e:
        code = getattr(e, "errno", None)
        name = errno.errorcode.get(code, "") if code else ""
        reason = _ERRNO_ZH.get(name)
        if not reason:
            reason = str(e) or "未知原因"
        return False, reason


def clean_contents(path):
    """清空目录内容（保留目录本身）。

    返回 (删除条目数, 失败数, 失败详情列表)；
    失败详情为 [{"name": 条目名, "reason": 原因}, ...]，最多记 8 条。
    """
    try:
        entries = os.listdir(path)
    except Exception as e:
        code = getattr(e, "errno", None)
        name = errno.errorcode.get(code, "") if code else ""
        reason = _ERRNO_ZH.get(name) or str(e)
        return 0, 0, [{"name": path, "reason": reason}]
    ok_n = fail_n = 0
    fails = []
    for fname in entries:
        ok, reason = _clean_entry(os.path.join(path, fname))
        if ok:
            ok_n += 1
        else:
            fail_n += 1
            if len(fails) < 8:
                fails.append({"name": fname, "reason": reason})
    return ok_n, fail_n, fails


def api_clean_scan(q):
    """并行扫描所有白名单目标的大小。只读，不删任何东西。"""
    items = []

    def probe(key, label, raw, risk, desc):
        path = os.path.expanduser(raw) if raw else ""
        exists = bool(path) and os.path.isdir(path)
        size = _du_size(path) if exists else 0
        if key == DSSTORE_KEY:
            files = dsstore_files()
            exists = len(files) > 0
            size = sum((os.path.getsize(f) for f in files if os.path.isfile(f)), 0)
            return {"key": key, "label": label, "path": "桌面 / 文稿 / 下载 / Sites（限 4 层深）",
                    "risk": risk, "desc": desc, "exists": exists, "size": size}
        return {"key": key, "label": label, "path": raw, "risk": risk, "desc": desc,
                "exists": exists, "size": size}

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(probe, k, l, p, r, d) for k, l, p, r, d in CLEAN_TARGETS]
        for f in futs:
            items.append(f.result())

    items.sort(key=lambda x: (-x["risk"], -x["size"]))
    return {"ok": True, "items": items, "total": sum(i["size"] for i in items)}


def api_clean_clean(q):
    """执行清理。只接受白名单 key，嵌套目录（子目录已被父目录覆盖）自动跳过。"""
    raw = (q.get("keys") or [""])[0]
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        return {"ok": False, "err": "未指定要清理的项目"}, 400

    valid = {t[0]: t for t in CLEAN_TARGETS}
    picked = []
    for k in keys:
        if k not in valid:
            return {"ok": False, "err": f"不支持的清理项: {k}"}, 400
        picked.append(valid[k])

    # 深路径先删，父目录覆盖到的子目录跳过（如 Caches 覆盖 Homebrew 缓存）
    picked.sort(key=lambda t: len(os.path.expanduser(t[2] or "")), reverse=True)
    removed_paths = []
    results = []
    freed_total = 0

    for key, label, raw_path, risk, desc in picked:
        if key == DSSTORE_KEY:
            files = dsstore_files()
            freed = sum((os.path.getsize(f) for f in files if os.path.isfile(f)), 0)
            n = fail_n = 0
            fails = []
            for f in files:
                ok, reason = _clean_entry(f)
                if ok:
                    n += 1
                else:
                    fail_n += 1
                    if len(fails) < 8:
                        fails.append({"name": os.path.basename(f), "reason": reason})
            freed_total += freed
            results.append({"key": key, "removed": n, "freed": freed,
                            "err": f"{fail_n} 个条目未能删除" if fail_n else "",
                            "fails": fails})
            continue
        path = os.path.expanduser(raw_path)
        if not os.path.isdir(path):
            results.append({"key": key, "removed": 0, "freed": 0,
                            "err": "目录不存在（可能已清理过）", "fails": []})
            continue
        if any(path == r or path.startswith(r + os.sep) for r in removed_paths):
            results.append({"key": key, "removed": 0, "freed": 0,
                            "err": "已随上级目录一并清理", "fails": []})
            continue
        size = _du_size(path)
        ok_n, fail_n, fails = clean_contents(path)
        removed_paths.append(path)
        freed_total += size
        results.append({"key": key, "removed": ok_n, "freed": size,
                        "err": f"{fail_n} 个条目未能删除" if fail_n else "",
                        "fails": fails})

    return {"ok": True, "results": results, "freed_total": freed_total}


ROUTES = {
    "/api/ping": api_ping,
    "/api/services": api_services,
    "/api/service/act": api_service_act,
    "/api/ports": api_ports,
    "/api/outdated": api_outdated,
    "/api/open": api_open,
    "/api/reveal": api_reveal,
    "/api/terminal": api_terminal,
    "/api/editor": api_editor,
    "/api/newfile": api_newfile,
    "/api/health": api_health,
    "/api/kill": api_kill,
    "/api/disk": api_disk,
    "/api/clean/scan": api_clean_scan,
    "/api/clean/execute": api_clean_clean,
}


# ─────────────────────────────── HTTP 服务 ───────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "MacToolBridge/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默，不污染终端

    def _send(self, body, ctype="application/json; charset=utf-8", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path in ("/", "/index.html", "/workspace"):
            try:
                with open(PAGE_FILE, "r", encoding="utf-8") as f:
                    return self._send(f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send("<h1>404</h1><p>未找到 mactool-workspace.html，请确认与 bridge 在同一目录。</p>",
                                  "text/html; charset=utf-8", 404)

        fn = ROUTES.get(u.path)
        if not fn:
            return self._send({"ok": False, "err": "404 not found"}, code=404)
        try:
            res = fn(q)
            if isinstance(res, tuple):
                return self._send(res[0], code=res[1])
            return self._send(res)
        except Exception as e:
            return self._send({"ok": False, "err": f"bridge 内部错误: {e}"}, code=500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def port_free(p):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", p))
            return True
        except OSError:
            return False


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8899
    port = start
    while not port_free(port) and port < start + 20:
        port += 1
    if not port_free(port):
        print("找不到可用端口，请手动指定。", file=sys.stderr)
        sys.exit(1)

    srv = Server(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print("")
    print("  Mac 工具管理台 · 本地服务已启动")
    print("  ─────────────────────────────────────────")
    print(f"  打开工作台：{url}")
    print(f"  页面文件  ：{PAGE_FILE}")
    print("")
    print("  安全边界：只监听 127.0.0.1 ｜ 仅白名单动作 ｜ 不提供任意命令执行")
    print("  停止服务：Ctrl + C")
    print("")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
        srv.server_close()


if __name__ == "__main__":
    main()
