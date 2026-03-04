from pathlib import Path
import datetime
import configparser
import threading
import time
import unicodedata
import json
import winsound
if not hasattr(winsound, "SND_SYNC"):
    winsound.SND_SYNC = 0x0000
if not hasattr(winsound, "SND_ASYNC"):
    winsound.SND_ASYNC = 0x0001
if not hasattr(winsound, "SND_filename"):
    pass
if not hasattr(winsound, "SND_FILENAME"):
    winsound.SND_FILENAME = 0x00020000
if not hasattr(winsound, "SND_MEMORY"):
    winsound.SND_MEMORY = 0x0004
if not hasattr(winsound, "SND_PURGE"):
    winsound.SND_PURGE = 0x0040
import wave
import array
import queue
try:
    import audioop
except ImportError:
    audioop = None

from .vendor_loader import load_runtime, runtime_scope

def _identity(text):
    return text


_cached_translate = _identity

def _t(msg):
    return _cached_translate(msg)

def _nt(singular, plural, n):
    return _t(singular) if n == 1 else _t(plural)

BASE_DIR = Path(__file__).resolve().parent
LIB_DIR = BASE_DIR / "lib"
_RUNTIME = load_runtime(str(LIB_DIR))

CONFIG_PATH = BASE_DIR / "config.ini"
LOG_DIR = Path.home() / "Documents" / "TikTok live"
COMMENTS_FILE = LOG_DIR / "comments.txt"
FOLLOWERS_FILE = LOG_DIR / "followers.txt"
GIFTS_FILE = LOG_DIR / "gifts.txt"
LIKES_FILE = LOG_DIR / "likes.txt"
STATS_FILE = LOG_DIR / "stats.txt"
TOP_GIFTERS_FILE = LOG_DIR / "top gifters.txt"
TOP_LIKES_FILE = LOG_DIR / "top likes.txt"
VISITORS_FILE = LOG_DIR / "visitors.txt"
SHARES_FILE = LOG_DIR / "shares.txt"
REQUESTS_FILE = LOG_DIR / "requests.txt"
EVENTS_FILE = LOG_DIR / "events.txt"
SPEECH_BUFFER_FILE = BASE_DIR / "speechbuffer.json"

_known_gifts = {}

def _clear_speech_buffer():
    try:
        with open(SPEECH_BUFFER_FILE, "w", encoding="utf-8") as f:
            pass
    except Exception:
        pass

client = None
_thread = None
_stats_thread = None
_run_lock = threading.Lock()
_client_loop = None
_stop_event = threading.Event()
_top_thread_started = False
_should_run = False


class LikeManager:
    def __init__(self):
        self._timers = {}
        
        self._baselines = {}
        self._current_totals = {}
        
        self._lock = threading.Lock()

    def add_like(self, user, current_api_total):
        with self._lock:
            if user in self._timers:
                self._timers[user].cancel()
                
            if user not in self._baselines:
                self._baselines[user] = self._current_totals.get(user, 0)
                
            self._current_totals[user] = current_api_total
            
            t = threading.Timer(10.0, self._flush, args=[user])
            t.daemon = True
            self._timers[user] = t
            t.start()

    def _flush(self, user):
        with self._lock:
            if user in self._timers:
                del self._timers[user]
                
            baseline = self._baselines.pop(user, 0)
            current = self._current_totals.get(user, 0)
            
            count = current - baseline
            
        if count <= 0:
            return
        
        likes_word = _nt("like", "likes", count)
        log_line = f"{user}: {count} {likes_word}  {datetime.datetime.now().strftime('%H:%M:%S')}"
        try:
            with open(LIKES_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass
            
        
        if PREFS.get("likes", False):
             _log_to_events(log_line)
        
        speak_line = f"{user}: {count} {likes_word}"

        if SETTINGS_OPEN:
            return

        event_key = "likes"
        sound_enabled = PLAY_SOUNDS and PREFS.get(event_key, False)
        speech_enabled = AUTO_SPEAK_PREFS.get(event_key, False)

        if _connection_time == 0 or (time.time() - _connection_time) < 10.0:
            sound_enabled = False
            speech_enabled = False

        if sound_enabled or speech_enabled:
            cb = None
            if speech_enabled:
                def _on_complete():
                    _speak_text(speak_line)

                cb = _on_complete

            sound_manager.play(event_key, play_file=sound_enabled, on_complete=cb)

    def stop(self):
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
            self._baselines.clear()
            self._current_totals.clear()

like_manager = LikeManager()


class SoundManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.sounds_dir = base_dir.parent.parent / "sounds"
        self.volume = 100
        self._queue = queue.Queue()
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def set_volume(self, volume):
        self.volume = max(0, min(100, int(volume)))

    def stop(self):
        self._running = False
        with self._queue.mutex:
            self._queue.queue.clear()

    def clear(self):
        with self._queue.mutex:
            self._queue.queue.clear()

    def start(self):
        if not self._running:
            self._queue = queue.Queue()
            self._running = True
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def play(self, event_name, play_file=True, on_complete=None, post_delay=1.0):
        
        mapping = {
            "comments": "comment.wav",
            "followers": "follower.wav",
            "gifts": "gift.wav",
            "likes": "like.wav",
            "shares": "share.wav",
            "visitors": "visitor.wav",
            "requests": "request.wav"
        }
        
        fname = mapping.get(event_name, f"{event_name}.wav")
        self._queue.put((fname, play_file, on_complete, post_delay))

    def _worker(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            
            fname = None
            play_file = True
            cb = None
            post_delay = 1.0

            if isinstance(item, tuple):
                if len(item) == 4:
                    fname, play_file, cb, post_delay = item
                elif len(item) == 3:
                     fname, play_file, cb = item
                elif len(item) == 2:
                    fname, cb = item
                    play_file = True
                else:
                    fname = item[0]
            else:
                fname = item

            if fname and play_file:
                self._play_actual(fname)
                
            if cb:
                try:
    
                    cb()
                except Exception:
                    pass

            if post_delay > 0:
                time.sleep(post_delay)
            
            self._queue.task_done()

    def _play_actual(self, fname):
        fpath = self.sounds_dir / fname
        
        if not fpath.exists():
            return

        try:
            with wave.open(str(fpath), 'rb') as wav_in:
                params = wav_in.getparams()
                
                if self.volume == 100:
                    winsound.PlaySound(str(fpath), winsound.SND_FILENAME | winsound.SND_SYNC)
                    return

                if params.sampwidth != 2:
                    winsound.PlaySound(str(fpath), winsound.SND_FILENAME | winsound.SND_SYNC)
                    return

                frames = wav_in.readframes(params.nframes)
                
                try:
                    
                    factor = self.volume / 100.0
                    
                    samples = array.array('h', frames)
                    
                    for i in range(len(samples)):
                        val = int(samples[i] * factor)
                        if val > 32767:
                            val = 32767
                        if val < -32768:
                            val = -32768
                        samples[i] = val
                        
                    data = samples.tobytes()
                    
                    import io
                    mem_file = io.BytesIO()
                    with wave.open(mem_file, 'wb') as wav_out:
                        wav_out.setparams(params)
                        wav_out.writeframes(data)
                    
                    mem_file.seek(0)
                    winsound.PlaySound(mem_file.read(), winsound.SND_MEMORY | winsound.SND_SYNC)
                    
                except Exception:
                    winsound.PlaySound(str(fpath), winsound.SND_FILENAME | winsound.SND_SYNC)
                
        except Exception:
            try:
                winsound.PlaySound(str(fpath), winsound.SND_FILENAME | winsound.SND_SYNC)
            except Exception:
                pass

sound_manager = SoundManager(BASE_DIR)

top_gifters = {}
top_likers = {}
total_likes = 0
total_followers = 0
total_diamonds = 0
visitors = set()
viewer_count = 0
total_viewers = 0
_known_processed_ids = set()
_known_comments = set()
_known_events = set()
_requests_log = {}
_known_users = {}
_known_followers = set()
_known_shares = {}
_processed_ids = set()
_connection_time = 0
_last_access_control_time = 0.0

AUTO_SPEAK_PREFS = {}
PLAY_SOUNDS = True
SOUND_VOLUME = 100
SETTINGS_OPEN = False

def set_settings_open(is_open):
    global SETTINGS_OPEN
    SETTINGS_OPEN = is_open

def _is_processed(event):
    uid = getattr(event, "msgId", None)
    if not uid:
        uid = getattr(event, "id", None)
    if not uid:
        base_msg = getattr(event, "base_message", None)
        if base_msg:
            uid = getattr(base_msg, "msg_id", None)
            
    if uid:
        if uid in _processed_ids:
            return True
        _processed_ids.add(uid)
        if len(_processed_ids) > 10000:
            _processed_ids.clear() 
    return False

def _load_config():
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH, encoding="utf-8")
        username = config.get("main", "username", fallback="")
    else:
        username = ""
        config["main"] = {"username": "your_username_here"}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            config.write(f)
            
    clear_on_start = config.getboolean("behavior", "clear_on_start", fallback=True)
    clean_usernames = config.getboolean("behavior", "clean_usernames", fallback=False)
    
    if "events" not in config and "auto_read" in config:
        config["events"] = config["auto_read"]
        
    if "events" not in config:
        config["events"] = {
            "comments": "true", "followers": "false", "gifts": "false",
            "likes": "false", "shares": "false", "visitors": "false", "requests": "true",
        }
        
    if "auto_speak" not in config:
        config["auto_speak"] = {
            "comments": "true", "followers": "false", "gifts": "false",
            "likes": "false", "shares": "false", "visitors": "false", "requests": "true",
        }
        
    prefs = {
        "comments": config.getboolean("events", "comments", fallback=True),
        "followers": config.getboolean("events", "followers", fallback=False),
        "gifts": config.getboolean("events", "gifts", fallback=False),
        "likes": config.getboolean("events", "likes", fallback=False),
        "shares": config.getboolean("events", "shares", fallback=False),
        "visitors": config.getboolean("events", "visitors", fallback=False),
        "requests": config.getboolean("events", "requests", fallback=True),
    }
    
    auto_speak_prefs = {
        "comments": config.getboolean("auto_speak", "comments", fallback=True),
        "followers": config.getboolean("auto_speak", "followers", fallback=False),
        "gifts": config.getboolean("auto_speak", "gifts", fallback=False),
        "likes": config.getboolean("auto_speak", "likes", fallback=False),
        "shares": config.getboolean("auto_speak", "shares", fallback=False),
        "visitors": config.getboolean("auto_speak", "visitors", fallback=False),
        "requests": config.getboolean("auto_speak", "requests", fallback=True),
    }
    
    play_sounds = config.getboolean("sounds", "play_sounds", fallback=False)
    volume = config.getint("sounds", "volume", fallback=100)
    inactivity_sound_count = config.getint("sounds", "inactivity_sound_count", fallback=1)
    
    return username, clear_on_start, clean_usernames, prefs, auto_speak_prefs, play_sounds, volume, inactivity_sound_count

try:
    USERNAME, _clear_on_start, CLEAN_USERNAMES, PREFS, AUTO_SPEAK_PREFS, PLAY_SOUNDS, SOUND_VOLUME, INACTIVITY_SOUND_COUNT = _load_config()
    sound_manager.set_volume(SOUND_VOLUME)
except Exception:
    USERNAME = ""
    _clear_on_start = True
    CLEAN_USERNAMES = False
    PREFS = {"comments": True}
    AUTO_SPEAK_PREFS = {"comments": True}
    PLAY_SOUNDS = True
    SOUND_VOLUME = 100
    INACTIVITY_SOUND_COUNT = 1

def update_config(username, prefs, auto_speak_prefs, play_sounds, volume, clear_on_start, clean_usernames, inactivity_sound_count=1):
    global USERNAME, PREFS, AUTO_SPEAK_PREFS, PLAY_SOUNDS, SOUND_VOLUME, _clear_on_start, CLEAN_USERNAMES, INACTIVITY_SOUND_COUNT
    
    if getattr(globals(), 'PLAY_SOUNDS', False) and not play_sounds:
        try:
            with sound_manager._queue.mutex:
                sound_manager._queue.queue.clear()
        except Exception:
            pass

    USERNAME = username
    PREFS = prefs
    AUTO_SPEAK_PREFS = auto_speak_prefs
    PLAY_SOUNDS = play_sounds
    SOUND_VOLUME = volume
    _clear_on_start = clear_on_start
    CLEAN_USERNAMES = clean_usernames
    INACTIVITY_SOUND_COUNT = inactivity_sound_count
    sound_manager.set_volume(volume)

def _sanitize_name(name):
    if not CLEAN_USERNAMES or not isinstance(name, str):
        return name
    out = []
    for ch in name:
        cat = unicodedata.category(ch)
        if ch.isspace() or cat.startswith("P"):
            out.append(ch)
        elif cat == "Nd":
            out.append(ch)
        elif cat[0] == "L":
            uname = unicodedata.name(ch, "")
            if "LATIN" in uname or "CYRILLIC" in uname:
                out.append(ch)
    return "".join(out).strip()

def _clear_all_text_files():
    for file in [
        COMMENTS_FILE, FOLLOWERS_FILE, GIFTS_FILE, TOP_GIFTERS_FILE,
        STATS_FILE, TOP_LIKES_FILE, LIKES_FILE, VISITORS_FILE, EVENTS_FILE, SHARES_FILE, REQUESTS_FILE
    ]:
        with open(file, "w", encoding="utf-8"):
            pass

def reset_accumulators():
    global top_gifters, top_likers, total_likes, total_followers, total_diamonds, visitors, viewer_count, total_viewers
    global _known_comments, _known_events, _known_followers, _known_shares, _requests_log, _processed_ids
    top_gifters = {}
    top_likers = {}
    total_likes = 0
    total_followers = 0
    total_diamonds = 0
    visitors = set()
    viewer_count = 0
    total_viewers = 0
    
    _known_comments.clear()
    _known_events.clear()
    _known_followers.clear()
    _known_shares.clear()
    _requests_log.clear()
    _processed_ids.clear()
    _known_gifts.clear()

def _ensure_files_exist():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for file in [
        COMMENTS_FILE, FOLLOWERS_FILE, GIFTS_FILE, TOP_GIFTERS_FILE,
        STATS_FILE, TOP_LIKES_FILE, LIKES_FILE, VISITORS_FILE, SHARES_FILE, REQUESTS_FILE, EVENTS_FILE
    ]:
        if not file.exists():
            with open(file, "w", encoding="utf-8"):
                pass

def update_stats_file():
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        f.write(_t("Viewers: {count}").format(count=viewer_count) + "\n")
        f.write(_t("Visitors: {count}").format(count=total_viewers) + "\n")
        f.write(_t("Likes: {count}").format(count=total_likes) + "\n")
        f.write(_t("Followers: {count}").format(count=total_followers) + "\n")
        f.write(_t("Diamonds: {count}").format(count=total_diamonds) + "\n")

def update_top_files():
    while not _stop_event.is_set():
        if top_gifters:
            sorted_gifters = sorted(top_gifters.items(), key=lambda x: x[1], reverse=True)
            with open(TOP_GIFTERS_FILE, "w", encoding="utf-8") as f:
                for user, diamonds in sorted_gifters:
                    f.write(f"{user}: {diamonds} diamonds\n")
        if top_likers:
            sorted_likers = sorted(top_likers.items(), key=lambda x: x[1], reverse=True)
            with open(TOP_LIKES_FILE, "w", encoding="utf-8") as f:
                for user, likes in sorted_likers:
                    f.write(f"{user}: {likes}\n")
        _stop_event.wait(10)

def _log_to_events(log_text):
    event_text = log_text.rsplit("  ", 1)[0]
    if event_text in _known_events:
        return
    _known_events.add(event_text)
    try:
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(log_text + "\n")
    except Exception:
        pass

def _speak_text(text):
    try:
        with open(SPEECH_BUFFER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _extract_comment_payload(event):
    user = getattr(event, "user", None)
    nickname = getattr(user, "nickname", None) or getattr(user, "unique_id", None) or "someone"
    nickname = _sanitize_name(nickname)
    uid = getattr(user, "id", getattr(user, "uid", None))
    if uid:
        _known_users[str(uid)] = nickname

    comment_text = (
        getattr(event, "comment", None)
        or getattr(event, "content", None)
        or getattr(event, "text", None)
        or getattr(event, "msg", None)
        or getattr(event, "message", None)
    )
    if not comment_text:
        comments_attr = getattr(event, "comments", None)
        if isinstance(comments_attr, (list, tuple)) and comments_attr:
            comment_text = " ".join(str(x) for x in comments_attr if x is not None).strip()

    if not comment_text:
        display_text = getattr(event, "display_text", None)
        comment_text = getattr(display_text, "default_pattern", None) or getattr(display_text, "key", None)

    if not comment_text:
        return None

    return nickname, str(comment_text)

def _handle_speech_and_sound(event_key, speak_text):
    """
    Handles sound playing and speech queuing with delay.
    event_key: 'comments', 'followers', etc.
    speak_text: The text to speak.
    """
    if SETTINGS_OPEN:
        return
        
    sound_enabled = PLAY_SOUNDS and PREFS.get(event_key, False)
    speech_enabled = AUTO_SPEAK_PREFS.get(event_key, False)
    
    if _connection_time == 0:
        sound_enabled = False
        speech_enabled = False
    elif (time.time() - _connection_time) < 10.0:
        if sound_enabled:
            sound_enabled = False
        if speech_enabled:
            speech_enabled = False

    if sound_enabled or speech_enabled:
        cb = None
        if speech_enabled:
            def _on_complete():
                _speak_text(speak_text)

            cb = _on_complete
            
        sound_manager.play(event_key, play_file=sound_enabled, on_complete=cb)
    else:
        pass

def _track_user(event):
    user = getattr(event, "user", None)
    if user:
        uid = getattr(user, "id", getattr(user, "uid", None))
        nn = getattr(user, "nick_name", getattr(user, "nickname", None))
        if uid and nn:
            _known_users[str(uid)] = _sanitize_name(nn)

def _apply_like_event(ev):
    global total_likes
    
    _track_user(ev)
    
    if hasattr(ev, "totalLikeCount"):
        total_likes = ev.totalLikeCount
    elif hasattr(ev, "total"):
        total_likes = ev.total
    elif hasattr(ev, "totalDiggCount"):
        total_likes = ev.totalDiggCount
        
    update_stats_file()
    
    user_obj = getattr(ev, "user", None)
    if not user_obj:
        return
        
    nick = getattr(user_obj, "nickname", None)
    unique_id = getattr(user_obj, "unique_id", None)
    
    raw_name = nick if nick else unique_id
    if not raw_name:
        return
        
    user_name = _sanitize_name(raw_name)
    if not user_name:
        return
        
    inc_candidates = ("likeCount", "count", "diggCount", "increment", "delta")
    inc_val = next((getattr(ev, a) for a in inc_candidates if hasattr(ev, a)), 0)
    increment = inc_val if (isinstance(inc_val, int) and inc_val > 0) else 1
    
    top_likers[user_name] = top_likers.get(user_name, 0) + increment
    update_stats_file()
    
    current_user_total = top_likers[user_name]
    like_manager.add_like(user_name, current_user_total)

async def on_comment(event):
    if not _should_run:
        return
    if _is_processed(event):
        return
    
    _track_user(event)
    
    payload = _extract_comment_payload(event)
    if not payload:
        return
    display_name, comment_text = payload
    user_comment = f"{display_name}: {comment_text}"
    if user_comment in _known_comments:
        return
    _known_comments.add(user_comment)
    log_line = f"{user_comment}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    with open(COMMENTS_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")
    if PREFS.get("comments", True):
        _log_to_events(log_line)
        
    _handle_speech_and_sound("comments", user_comment)

async def on_follow(event):
    if not _should_run:
        return
    if _is_processed(event):
        return
    
    _track_user(event)
    
    global total_followers
    
    unique_id = getattr(event.user, "unique_id", event.user.nickname)

    if unique_id in _known_followers:
        return
    _known_followers.add(unique_id)

    total_followers += 1
    nm = _sanitize_name(event.user.nickname)
    log_line = f"{nm}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    with open(FOLLOWERS_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")
    speak_msg = _t("New follower: {name}").format(name=nm)
    log_msg = f"{speak_msg}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    
    if PREFS.get("followers", False):
        _log_to_events(log_msg)
        
    _handle_speech_and_sound("followers", speak_msg)
    update_stats_file()

async def on_gift(event):
    if not _should_run:
        return
    if _is_processed(event):
        return
        
    _track_user(event)
    
    global total_diamonds
    if not getattr(event, "repeat_end", True):
        return
    count = getattr(event, "repeat_count", 1) or 1
    name = getattr(event.gift, "name", "Gift")
    diamonds = count * getattr(event.gift, "diamond_count", 0)
    display_name = _sanitize_name(getattr(event.user, "nickname", "someone"))
    
    gift_key = f"{display_name}_{name}_{count}"
    now = time.time()
    if now - _known_gifts.get(gift_key, 0) < 1.0:
        return
    _known_gifts[gift_key] = now
    
    if diamonds > 0:
        total_diamonds += diamonds
        top_gifters[display_name] = top_gifters.get(display_name, 0) + diamonds
    
    speak_msg = f"Gift: {display_name}: {count} {name}"
    log_msg = f"{speak_msg}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    
    file_line = f"{display_name}: {count} {name}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    
    with open(GIFTS_FILE, "a", encoding="utf-8") as f:
        f.write(file_line + "\n")
        
    if PREFS.get("gifts", False):
        _log_to_events(log_msg)
        
    _handle_speech_and_sound("gifts", speak_msg)
    update_stats_file()

async def on_like(event):
    if not _should_run:
        return
    _apply_like_event(event)

async def on_digg(event):
    if not _should_run:
        return
    _apply_like_event(event)

async def on_share(event):
    if not _should_run:
        return
    if _is_processed(event):
        return
        
    _track_user(event)
    
    display_name = _sanitize_name(event.user.nickname)
    
    now = time.time()
    if now - _known_shares.get(display_name, 0) < 1.0:
        return
    _known_shares[display_name] = now
    
    log_line = f"{display_name}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    
    with open(SHARES_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")
        
    if PREFS.get("shares", False):
        msg = _t("{name} shared the live").format(name=display_name)
        log_msg = f"{msg}  {datetime.datetime.now().strftime('%H:%M:%S')}"
        _log_to_events(log_msg)

    msg = _t("{name} shared the live").format(name=display_name)
    _handle_speech_and_sound("shares", msg)

async def on_social(event):
    if not _should_run:
        return
    
    action = getattr(event, "action", None)
    key = getattr(getattr(event, "display_text", None), "key", "").lower()
    default_fmt = getattr(getattr(event, "display_text", None), "default_pattern", "").lower()
    
    if action == 3 or "share" in key or "share" in default_fmt:
        await on_share(event)
        return

    if action == 1 or "follow" in key or "follow" in default_fmt:
        await on_follow(event)
        return

async def on_join(event):
    if not _should_run:
        return
    
    _track_user(event)
    
    global total_viewers
    user = getattr(event, "user", None)
    display_name = _sanitize_name(getattr(user, "nickname", "someone"))
    
    if display_name in visitors:
        return
    visitors.add(display_name)
    
    total_viewers = len(visitors)
    log_line = f"{display_name}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    with open(VISITORS_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")
    if PREFS.get("visitors", False):
        msg = _t("{name} joined").format(name=display_name)
        log_msg = f"{msg}  {datetime.datetime.now().strftime('%H:%M:%S')}"
        _log_to_events(log_msg)
    
    msg = _t("{name} joined").format(name=display_name)
    _handle_speech_and_sound("visitors", msg)
    update_stats_file()

def _trigger_access_control_logic(is_test=False):
    global _last_access_control_time
    if not _should_run and not is_test:
        return
        
    now = time.time()
    if (now - _last_access_control_time < 5.0) and not is_test:
        return
    _last_access_control_time = now
        
    speak_msg = _t("Inactivity check")
    log_line = f"{speak_msg}  {datetime.datetime.now().strftime('%H:%M:%S')}"
    
    if PREFS.get("captcha", False) or is_test:
        _log_to_events(log_line)
        
    if SETTINGS_OPEN and not is_test:
        return
        
    sound_enabled = PLAY_SOUNDS and PREFS.get("captcha", False)
    speech_enabled = AUTO_SPEAK_PREFS.get("captcha", False)
    
    if is_test:
        sound_enabled = True
        speech_enabled = True
    
    if (_connection_time == 0 or (time.time() - _connection_time) < 10.0) and not is_test:
        sound_enabled = False
        speech_enabled = False

    if sound_enabled or speech_enabled:
        cb = None
        if speech_enabled:
            def _on_complete():
                _speak_text(speak_msg)
            cb = _on_complete
            
        if sound_enabled:
            for i in range(INACTIVITY_SOUND_COUNT):
                is_last = (i == INACTIVITY_SOUND_COUNT - 1)
                sound_manager.play("captcha", play_file=True, on_complete=cb if is_last else None, post_delay=1.0)
        else:
            if cb:
                sound_manager.play("captcha", play_file=False, on_complete=cb, post_delay=0.0)

async def on_access_control(event):
    _trigger_access_control_logic(is_test=False)

async def on_viewer_update(event):
    if not _should_run:
        return
    global viewer_count
    if hasattr(event, "m_total"):
        viewer_count = event.m_total
    elif hasattr(event, "viewer_count"):
        viewer_count = event.viewer_count
    update_stats_file()

async def on_guest_request(event):
    if not _should_run:
        return
    
    try:
        user_name = None
        is_request = False
        
        def _get_name_from_user(u):
            if not u: return None
            uid = getattr(u, "id", getattr(u, "uid", None))
            nn = getattr(u, "nick_name", getattr(u, "nickname", None))
            if nn:
                sanitized = _sanitize_name(nn)
                if sanitized:
                    if uid: _known_users[str(uid)] = sanitized
                    return sanitized
            if uid and str(uid) in _known_users:
                return _known_users[str(uid)]
            return None

        if hasattr(event, "apply_content") and event.apply_content is not None:
            is_request = True
            name = _get_name_from_user(getattr(event.apply_content, "applicant", None))
            if name: user_name = name

        if not user_name and hasattr(event, "invite_content") and event.invite_content is not None:
            is_request = True
            name = _get_name_from_user(getattr(event.invite_content, "invitee", None))
            if name: user_name = name
                
        if not user_name and hasattr(event, "user") and event.user is not None:
            name = _get_name_from_user(event.user)
            if name: user_name = name
                
        if not user_name and hasattr(event, "inviter_nickname") and event.inviter_nickname:
            sanitized = _sanitize_name(event.inviter_nickname)
            if sanitized:
                user_name = sanitized
            is_request = True

        if not user_name and hasattr(event, "base_message") and event.base_message:
            dt = getattr(event.base_message, "display_text", None)
            if dt and hasattr(dt, "pieces") and dt.pieces:
                for piece in dt.pieces:
                    uv = getattr(piece, "user_value", None)
                    if uv and hasattr(uv, "user"):
                        name = _get_name_from_user(uv.user)
                        if name:
                            user_name = name
                            break
                            
        if not user_name and hasattr(event, "list_content") and event.list_content:
            lc = event.list_content
            change_type = getattr(lc, "list_change_type", None)
            if change_type is not None and change_type not in (1, 2):
                return
            if hasattr(lc, "user_list") and lc.user_list:
                ul = lc.user_list
                if hasattr(ul, "applied_list") and ul.applied_list:
                    for app in ul.applied_list:
                        if hasattr(app, "link_user") and app.link_user:
                            name = _get_name_from_user(app.link_user)
                            if name:
                                user_name = name
                                is_request = True
                                break

        mtype = str(getattr(event, "message_type", ""))
        if "Apply" in mtype or "APPLY" in mtype:
            is_request = True
            
        m_t = str(getattr(event, "m_type", getattr(event, "mType", "")))
        if m_t in ("1", "2"):
            is_request = True
        elif m_t == "8":
            return
            
        ename = type(event).__name__
        if ename in ("LinkMicMethodEvent", "GuestInviteEvent", "LinkLayerEvent", 
                     "WebcastLinkLayerMessage", "WebcastLinkMicMethodMessage", "WebcastGuestInviteMessage"):
            is_request = True
            
        if not is_request:
            return
            
        if not user_name:
            return
            
        now = time.time()
        if now - _requests_log.get(user_name, 0) < 10.0:
            return
        _requests_log[user_name] = now
            
        speak_msg = _t("Guest request: {name}").format(name=user_name)
        
        log_line = f"{user_name}  {datetime.datetime.now().strftime('%H:%M:%S')}"
        with open(REQUESTS_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
            
        if PREFS.get("requests", True):
            log_msg = f"{speak_msg}  {datetime.datetime.now().strftime('%H:%M:%S')}"
            _log_to_events(log_msg)
            
        _handle_speech_and_sound("requests", speak_msg)
        
    except Exception as e:
        pass

def setup():
    _ensure_files_exist()
    return True

def _runner(username, on_connect_cb, on_retry_cb, on_fail_cb, max_attempts=3):
    global client
    attempts = 0
    connected_once = False

    try:
        with runtime_scope(_RUNTIME):
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import CommentEvent, FollowEvent, GiftEvent, LikeEvent, DiggEvent, JoinEvent, ConnectEvent, AccessControlEvent, ControlEvent
            try:
                from TikTokLive.events import CommentsEvent
            except ImportError:
                CommentsEvent = None
            try:
                from TikTokLive.events import EmoteChatEvent, ScreenChatEvent
            except ImportError:
                EmoteChatEvent = None
                ScreenChatEvent = None
            try:
                from TikTokLive.events import ViewerUpdateEvent, RoomUserSeqEvent
            except ImportError:
                try:
                    from TikTokLive.events import RoomUserSeqEvent
                    ViewerUpdateEvent = None
                except ImportError:
                    RoomUserSeqEvent = None
                    ViewerUpdateEvent = None
                    
            try:
                from TikTokLive.events import ShareEvent
            except ImportError:
                ShareEvent = None
                
            try:
                from TikTokLive.events import SocialEvent
            except ImportError:
                SocialEvent = None
                
            try:
                from TikTokLive.events import LinkLayerEvent
            except ImportError:
                LinkLayerEvent = None

            try:
                from TikTokLive.events import LinkMicMethodEvent
            except ImportError:
                LinkMicMethodEvent = None

            try:
                from TikTokLive.events import GuestInviteEvent
            except ImportError:
                GuestInviteEvent = None
    except Exception as e:
        if on_fail_cb:
            on_fail_cb()
        return

    while _should_run:
        try:
            with runtime_scope(_RUNTIME):
                client = TikTokLiveClient(unique_id=username)
                
                my_client = client
                def wrap(func):
                    async def wrapper(*args, **kwargs):
                        if globals().get('client') is not my_client:
                            return
                        await func(*args, **kwargs)
                    return wrapper

                client.add_listener(CommentEvent, wrap(on_comment))
                client.add_listener("CommentEvent", wrap(on_comment))
                if CommentsEvent:
                    client.add_listener(CommentsEvent, wrap(on_comment))
                    client.add_listener("CommentsEvent", wrap(on_comment))
                if EmoteChatEvent:
                    client.add_listener(EmoteChatEvent, wrap(on_comment))
                    client.add_listener("EmoteChatEvent", wrap(on_comment))
                if ScreenChatEvent:
                    client.add_listener(ScreenChatEvent, wrap(on_comment))
                    client.add_listener("ScreenChatEvent", wrap(on_comment))
                client.add_listener(FollowEvent, wrap(on_follow))
                client.add_listener(GiftEvent, wrap(on_gift))
                client.add_listener(LikeEvent, wrap(on_like))
                client.add_listener(DiggEvent, wrap(on_digg))
                client.add_listener(JoinEvent, wrap(on_join))
                client.add_listener(AccessControlEvent, wrap(on_access_control))
                client.add_listener("AccessControlEvent", wrap(on_access_control))
                client.add_listener(ControlEvent, wrap(on_access_control))
                client.add_listener("ControlEvent", wrap(on_access_control))
                if ShareEvent:
                    try:
                        client.add_listener(ShareEvent, wrap(on_share))
                    except Exception:
                        pass
                if SocialEvent:
                    try:
                        client.add_listener(SocialEvent, wrap(on_social))
                    except Exception:
                        pass
                if ViewerUpdateEvent:
                    client.add_listener(ViewerUpdateEvent, wrap(on_viewer_update))
                if RoomUserSeqEvent:
                    client.add_listener(RoomUserSeqEvent, wrap(on_viewer_update))
                    
                if LinkLayerEvent:
                    client.add_listener(LinkLayerEvent, wrap(on_guest_request))
                    client.add_listener("LinkLayerEvent", wrap(on_guest_request))
                if LinkMicMethodEvent:
                    client.add_listener(LinkMicMethodEvent, wrap(on_guest_request))
                    client.add_listener("LinkMicMethodEvent", wrap(on_guest_request))
                if GuestInviteEvent:
                    client.add_listener(GuestInviteEvent, wrap(on_guest_request))
                    client.add_listener("GuestInviteEvent", wrap(on_guest_request))
                
                client.add_listener("WebcastLinkLayerMessage", wrap(on_guest_request))
                client.add_listener("WebcastLinkMicMethodMessage", wrap(on_guest_request))
                client.add_listener("WebcastGuestInviteMessage", wrap(on_guest_request))
                


                async def on_connected(event):
                    nonlocal attempts, connected_once
                    global _connection_time
                    attempts = 0
                    connected_once = True
                    _connection_time = time.time()
                    if on_connect_cb:
                        on_connect_cb()
                        
                client.add_listener(ConnectEvent, on_connected)
                
                global _client_loop
                import asyncio
                try:
                    _client_loop = asyncio.get_event_loop()
                except RuntimeError:
                    _client_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(_client_loop)
                
                client.run()
            
        except Exception:
            import traceback
            pass
        
        if not _should_run:
            break
            
        attempts += 1
        if attempts < max_attempts:
            if on_retry_cb:
                on_retry_cb()
            time.sleep(3)
        else:
            if on_fail_cb:
                on_fail_cb()
            break

def connect(username=None, on_connect=None, on_retry=None, on_fail=None, retry_count=3):
    global _top_thread_started, USERNAME, CLEAN_USERNAMES, _thread, _should_run, _stats_thread, _known_comments, _known_events
    global _known_followers, _known_shares, PREFS, AUTO_SPEAK_PREFS, PLAY_SOUNDS, SOUND_VOLUME, INACTIVITY_SOUND_COUNT, _processed_ids, _connection_time
    
    USERNAME, clear_on_start, CLEAN_USERNAMES, PREFS, AUTO_SPEAK_PREFS, PLAY_SOUNDS, SOUND_VOLUME, INACTIVITY_SOUND_COUNT = _load_config()
    sound_manager.set_volume(SOUND_VOLUME)
    sound_manager.start()
    sound_manager.clear()
    _clear_speech_buffer()
    _known_comments = set()
    _known_events = set()
    _processed_ids = set()
    _known_gifts.clear()
    _connection_time = 0
    _known_followers = set()
    _known_shares = {}
    if not clear_on_start:
        try:
            for ln in COMMENTS_FILE.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if ln:
                    parts = ln.rsplit("  ", 1)
                    _known_comments.add(parts[0])
            if EVENTS_FILE.exists():
                for ln in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
                    ln = ln.strip()
                    if ln:
                        parts = ln.rsplit("  ", 1)
                        _known_events.add(parts[0])
        except Exception:
            pass
    final_user = username if username else USERNAME
    
    if not final_user:
        return

    _ensure_files_exist()
    if clear_on_start:
        _clear_all_text_files()
        reset_accumulators()
        update_stats_file()

    _stop_event.clear()
    
    if not _top_thread_started:
        _stats_thread = threading.Thread(target=update_top_files, daemon=True)
        _stats_thread.start()
        _top_thread_started = True

    _should_run = True
    
    with _run_lock:
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(target=_runner, args=(final_user, on_connect, on_retry, on_fail, retry_count), daemon=True)
        _thread.start()

def disconnect():
    global _thread, client, _should_run, _top_thread_started, _stats_thread
    _should_run = False
    _stop_event.set()
    
    _stats_thread = None
    _top_thread_started = False
    
    with _run_lock:
        if client:
            try:
                if '_client_loop' in globals() and _client_loop is not None and getattr(client, "connected", False):
                    if _client_loop.is_running():
                        _client_loop.call_soon_threadsafe(client.stop)
                else:
                    client.stop()
            except Exception:
                pass
        
        like_manager.stop()
        
        if 'sound_manager' in globals():
            sound_manager.stop()
        
        old_thread = _thread
        _thread = None
        client = None
        
    if old_thread and old_thread.is_alive() and old_thread != threading.current_thread():
        try:
            old_thread.join(timeout=3.0)
        except Exception:
            pass

if __name__ == "__main__":
    setup()
    connect()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        disconnect()
