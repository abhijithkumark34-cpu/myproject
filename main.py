"""
main.py — Flappy Bird clone with 6s splash and a predictive multi-flap secret autoplay bot.
Press 'A' to toggle the secret bot.
"""

import os
import random
import time
import wave
from PIL import Image as PILImage

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.properties import NumericProperty, BooleanProperty, StringProperty
from kivy.uix.widget import Widget
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.button import Button

# Optional sound backends
try:
    from kivy.core.audio import SoundLoader
except Exception:
    SoundLoader = None
try:
    import simpleaudio as sa
except Exception:
    sa = None
try:
    import pygame
    pygame_mixer_available = True
except Exception:
    pygame = None
    pygame_mixer_available = False
if os.name == 'nt':
    try:
        import winsound
    except Exception:
        winsound = None
else:
    winsound = None
try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None

# -------------------------
# Window / baseline values
# -------------------------
WINDOW_WIDTH = 400
WINDOW_HEIGHT = 600
Window.size = (WINDOW_WIDTH, WINDOW_HEIGHT)
Window.clearcolor = (0.5, 0.75, 1, 1)

# Gameplay constants
GRAVITY = -480.0
FLAP_VELOCITY = 380.0
BIRD_SIZE = (64, 64)
IMAGE_CONVERT_SIZE = (64, 64)
WHITE_THRESHOLD = 240
MIN_FLAP_INTERVAL = 0.18
PIPE_MIN_GAP_Y = 60

# Difficulty sets — kept the larger gaps from last step
EASY = {
    'PIPE_SPEED': 80.0,
    'PIPE_GAP': 300,
    'PIPE_SPAWN_INTERVAL': 4.0,
    'INITIAL_SPACING_MULT': 1.3
}
HARD = {
    'PIPE_SPEED': 180.0,
    'PIPE_GAP': 200,
    'PIPE_SPAWN_INTERVAL': 2.0,
    'INITIAL_SPACING_MULT': 1.05
}
RAMP_MAX_ADDITIONAL_SPEED = 80.0
RAMP_MAX_GAP_REDUCTION = 50

# -------------------------
# Helpers: image conversion
# -------------------------
def convert_jpg_to_png_with_transparency(folder, jpg_name='bird_face.jpg'):
    jpg_path = os.path.join(folder, jpg_name)
    png_name = os.path.splitext(jpg_name)[0] + '.png'
    png_path = os.path.join(folder, png_name)
    if os.path.exists(png_path):
        return png_path
    if not os.path.exists(jpg_path):
        return None
    try:
        img = PILImage.open(jpg_path).convert("RGBA")
        img.thumbnail(IMAGE_CONVERT_SIZE, PILImage.LANCZOS)
        bg = PILImage.new("RGBA", IMAGE_CONVERT_SIZE, (0, 0, 0, 0))
        x = (IMAGE_CONVERT_SIZE[0] - img.width) // 2
        y = (IMAGE_CONVERT_SIZE[1] - img.height) // 2
        bg.paste(img, (x, y), img)
        new_pixels = []
        for (r, g, b, a) in bg.getdata():
            if r >= WHITE_THRESHOLD and g >= WHITE_THRESHOLD and b >= WHITE_THRESHOLD:
                new_pixels.append((255, 255, 255, 0))
            else:
                new_pixels.append((r, g, b, a))
        bg.putdata(new_pixels)
        bg.save(png_path, "PNG")
        print("[Image] Converted JPG -> PNG:", png_path)
        return png_path
    except Exception as e:
        print("[Image] Conversion error:", e)
        return None

# -------------------------
# Sound helpers
# -------------------------
class DummySound:
    def play(self): pass
    def stop(self): pass

def is_standard_pcm_wav(path):
    try:
        with wave.open(path, 'rb') as w:
            return w.getcomptype() == 'NONE'
    except Exception:
        return False

def transcode_to_pcm_wav(original_path, out_path):
    if AudioSegment is None:
        print("[Sound] pydub not installed; cannot transcode automatically.")
        return False
    try:
        seg = AudioSegment.from_file(original_path)
        seg = seg.set_frame_rate(44100).set_channels(2).set_sample_width(2)
        seg.export(out_path, format='wav')
        print("[Sound] Transcoded to PCM WAV:", out_path)
        return True
    except Exception as e:
        print("[Sound] Transcode error:", e)
        return False

def make_play_wrappers(path):
    wrappers = {}
    if SoundLoader:
        try:
            s = SoundLoader.load(path)
            if s: wrappers['kivy'] = s
        except: pass
    if sa:
        try:
            wave_obj = sa.WaveObject.from_wave_file(path)
            class SAWrap:
                def __init__(self, wobj):
                    self.wobj = wobj
                    self._play = None
                def play(self):
                    try: self._play = self.wobj.play()
                    except: pass
                def stop(self):
                    try: self._play.stop()
                    except: pass
            wrappers['simpleaudio'] = SAWrap(wave_obj)
        except: pass
    if pygame:
        try:
            if not pygame.mixer.get_init(): pygame.mixer.init()
            snd = pygame.mixer.Sound(path)
            class PygWrap:
                def __init__(self, s):
                    self.s = s
                    self.chan = None
                def play(self):
                    try: self.chan = self.s.play()
                    except: pass
                def stop(self):
                    try: self.chan.stop()
                    except: pass
            wrappers['pygame'] = PygWrap(snd)
        except: pass
    if winsound:
        try:
            class WinWrap:
                def __init__(self, p): self.p = p
                def play(self):
                    try: winsound.PlaySound(self.p, winsound.SND_ASYNC | winsound.SND_FILENAME)
                    except: pass
                def stop(self):
                    try: winsound.PlaySound(None, winsound.SND_PURGE)
                    except: pass
            wrappers['winsound'] = WinWrap(path)
        except: pass
    return wrappers

# -------------------------
# Game classes
# -------------------------
class Bird(Widget):
    velocity = NumericProperty(0.0)
    source = StringProperty('')
    def __init__(self, source=None, **kwargs):
        super().__init__(**kwargs)
        self.size = BIRD_SIZE
        self.size_hint = (None, None)
        self.source = source or ''
        self._image_widget = None
        self._rect = None
        if self.source and os.path.exists(self.source):
            self._image_widget = Image(source=self.source, size=self.size, size_hint=(None, None))
            self.add_widget(self._image_widget)
        else:
            with self.canvas:
                Color(1, 0.6, 0.2, 1)
                self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_graphics, size=self._update_graphics)
    def _update_graphics(self, *a):
        if self._image_widget:
            self._image_widget.pos, self._image_widget.size = self.pos, self.size
        elif self._rect:
            self._rect.pos, self._rect.size = self.pos, self.size
    def physics_step(self, dt):
        self.velocity += GRAVITY * dt
        self.y += self.velocity * dt
    def flap(self): self.velocity = FLAP_VELOCITY
    @property
    def top(self): return self.y + self.height

class PipePair(Widget):
    scored = BooleanProperty(False)
    def __init__(self, x, gap_y, gap_size, width, screen_height, **kwargs):
        super().__init__(**kwargs)
        self.x = x
        self.width_pipe = width
        self.gap_size = gap_size
        self.gap_y = gap_y
        self.screen_height = screen_height
        self.bottom_height = gap_y
        self.top_pos = gap_y + gap_size
        self.top_height = screen_height - self.top_pos
        with self.canvas:
            Color(0.15, 0.65, 0.2, 1)
            self._bottom_rect = Rectangle(pos=(self.x, 0), size=(self.width_pipe, self.bottom_height))
            self._top_rect = Rectangle(pos=(self.x, self.top_pos), size=(self.width_pipe, self.top_height))
        self.size = (self.width_pipe, screen_height)
        self.pos = (self.x, 0)
    @property
    def right(self): return self.x + self.width_pipe
    def move(self, dx):
        self.x += dx
        self._bottom_rect.pos = (self.x, 0)
        self._top_rect.pos = (self.x, self.top_pos)
        self.pos = (self.x, 0)
    def collides_with(self, bx, by, bw, bh):
        bx1, by1, bw1, bh1 = self.x, 0, self.width_pipe, self.bottom_height
        tx1, ty1, tw1, th1 = self.x, self.top_pos, self.width_pipe, self.top_height
        def aabb(x1,y1,w1,h1, x2,y2,w2,h2): return (x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2)
        return aabb(bx, by, bw, bh, bx1, by1, bw1, bh1) or aabb(bx, by, bw, bh, tx1, ty1, tw1, th1)

# -------------------------
# Main game widget
# -------------------------
class FlappyGame(Widget):
    score = NumericProperty(0)
    game_over = BooleanProperty(False)
    running = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0.6,0.85,1,1)
            self._bg = Rectangle(size=Window.size, pos=self.pos)
        self.bind(size=self._update_bg, pos=self._update_bg)

        folder = os.path.dirname(os.path.abspath(__file__))
        converted = convert_jpg_to_png_with_transparency(folder, 'bird_face.jpg')
        png_path = converted or os.path.join(folder, 'bird_face.png')
        bird_source = png_path if os.path.exists(png_path) else None
        self.bird = Bird(source=bird_source)
        self.bird.pos = (100, WINDOW_HEIGHT // 2 - self.bird.height // 2)
        self.add_widget(self.bird)

        self.score_label = Label(text="Score: 0", pos=(10, WINDOW_HEIGHT - 40), size_hint=(None, None), font_size=26)
        self.add_widget(self.score_label)

        self.start_button = Button(text="Start Game", size_hint=(None, None), size=(160, 60),
                                   pos=(WINDOW_WIDTH / 2 - 80, WINDOW_HEIGHT / 2 - 30))
        self.start_button.bind(on_release=self.start_game)
        self.add_widget(self.start_button)

        # Sound setup
        self.sound_path = None
        sound_candidate = os.path.join(folder, 'sound.wav')
        if os.path.exists(sound_candidate):
            self.sound_path = sound_candidate
            if not is_standard_pcm_wav(self.sound_path):
                fixed = os.path.join(folder, 'sound_transcoded.wav')
                if transcode_to_pcm_wav(self.sound_path, fixed):
                    self.sound_path = fixed
        self.sound_wrappers = make_play_wrappers(self.sound_path) if self.sound_path else {}

        self.pipes = []
        self._time_since_last_spawn = 0.0
        Window.bind(on_key_down=self._on_key_down)
        self._update_event = None
        self._last_flap_time = 0.0

        # Difficulty initial
        self.current_pipe_speed = EASY['PIPE_SPEED']
        self.current_pipe_gap = EASY['PIPE_GAP']
        self.current_spawn_interval = EASY['PIPE_SPAWN_INTERVAL']
        self.initial_spacing_mult = EASY['INITIAL_SPACING_MULT']

        # Secret autoplay flag
        self.autoplay = False

    def _update_bg(self, *a):
        self._bg.size = self.size
        self._bg.pos = self.pos

    def _on_key_down(self, window, key, scancode, codepoint, modifiers):
        # Spacebar: start / flap
        if key == 32 or codepoint == ' ':
            if not self.running and not self.game_over:
                self.start_game(None)
            elif self.running:
                self._flap()
        # Secret toggle: A or a
        elif codepoint and codepoint.lower() == 'a':
            self.autoplay = not self.autoplay
            print("[Secret Bot] Autoplay:", self.autoplay)
            if self.autoplay and not self.running and not self.game_over:
                self.start_game(None)

    def on_touch_down(self, touch):
        if not self.running and not self.game_over:
            self.start_game(None)
        elif self.running:
            self._flap()
        return super().on_touch_down(touch)

    def _can_flap_now(self):
        now = time.time()
        if now - self._last_flap_time >= MIN_FLAP_INTERVAL:
            self._last_flap_time = now
            return True
        return False

    def _flap(self):
        if not self._can_flap_now(): return
        self.bird.flap()
        # play sound using first available wrapper
        for name in ('kivy','simpleaudio','pygame','winsound'):
            w = self.sound_wrappers.get(name)
            if w:
                try:
                    if hasattr(w,'stop'): w.stop()
                    w.play()
                    break
                except: pass

    # -------------------------
    # Predictive multi-flap controller
    # -------------------------
    def _predict_center_with_flaps(self, time_to_pipe, n_flaps):
        """
        Predict the bird center at time_to_pipe if we apply n_flaps.
        Flap schedule: if n_flaps >= 1, first flap at t=0 (now),
        further flaps at t = MIN_FLAP_INTERVAL, 2*MIN_FLAP_INTERVAL, ...
        """
        y = self.bird.y
        v = self.bird.velocity
        # build events: flap times (include 0 if n_flaps>=1) and final time
        events = []
        if n_flaps >= 1:
            for i in range(n_flaps):
                t = i * MIN_FLAP_INTERVAL
                # don't add flap events beyond time_to_pipe
                if t < time_to_pipe:
                    events.append(('flap', t))
        events.append(('end', time_to_pipe))
        # ensure events sorted
        events.sort(key=lambda x: x[1])
        t_prev = 0.0
        for event_type, t_event in events:
            dt = t_event - t_prev
            # integrate motion for dt
            # y(t+dt) = y + v*dt + 0.5*g*dt^2
            y = y + v * dt + 0.5 * GRAVITY * (dt ** 2)
            # v(t+dt) = v + g*dt
            v = v + GRAVITY * dt
            # if this event is a flap (and not the final), set velocity to FLAP_VELOCITY
            if event_type == 'flap':
                v = FLAP_VELOCITY
            t_prev = t_event
        # return center
        return y + (self.bird.height / 2.0)

    def _autoflap_logic(self):
        # basic guards
        if not self.pipes or not self.running or self.game_over:
            return

        # choose next pipe ahead of the bird (first with right edge ahead)
        next_pipe = None
        for p in self.pipes:
            if p.x + p.width_pipe > self.bird.x:
                next_pipe = p
                break
        if not next_pipe:
            return

        gap_center = next_pipe.gap_y + next_pipe.gap_size / 2.0
        horiz_dist = next_pipe.x - self.bird.x
        if self.current_pipe_speed <= 0:
            return
        time_to_pipe = horiz_dist / self.current_pipe_speed

        # try 0..3 flaps and pick the minimal flaps that land inside gap (with margin)
        margin = 6.0
        max_flaps = 3
        chosen_flaps = None
        for k in range(0, max_flaps + 1):
            predicted_center = self._predict_center_with_flaps(time_to_pipe, k)
            # check if predicted center will be inside pipe gap region (allow margin)
            if (gap_center - (next_pipe.gap_size / 2.0) + margin) <= predicted_center <= (gap_center + (next_pipe.gap_size / 2.0) - margin):
                chosen_flaps = k
                break

        # If chosen_flaps is None, we'll pick the k that gets closest above the lower edge (safer)
        if chosen_flaps is None:
            best_k = None
            best_dist = float('inf')
            for k in range(0, max_flaps + 1):
                predicted_center = self._predict_center_with_flaps(time_to_pipe, k)
                # distance from gap center
                dist = abs(predicted_center - gap_center)
                if dist < best_dist:
                    best_dist = dist
                    best_k = k
            chosen_flaps = best_k
    

        # If chosen_flaps >= 1, we need to flap now (first flap at t=0)
        if chosen_flaps is not None and chosen_flaps >= 1:
            # flap now (honors MIN_FLAP_INTERVAL via _can_flap_now)
            self._flap()
            # subsequent flaps (if chosen_flaps > 1) will be handled by repeated calls to this logic:
            # once MIN_FLAP_INTERVAL passes, this method will run again in the update loop and may schedule the next flap.
            # This avoids bypassing debounce forcibly.
        # else chosen_flaps == 0 -> do nothing

    # -------------------------
    # Game logic
    # -------------------------
    def start_game(self, instance):
        self.clear_pipes()
        self.score = 0
        self.score_label.text = "Score: 0"
        self.game_over = False
        self.running = True
        self._time_since_last_spawn = 0.0
        self.bird.pos = (100, WINDOW_HEIGHT // 2 - self.bird.height // 2)
        self.bird.velocity = 0.0
        if self.start_button.parent:
            self.remove_widget(self.start_button)

        spacing = int(WINDOW_WIDTH * self.initial_spacing_mult)
        for i in range(2):
            spawn_x = WINDOW_WIDTH + i * spacing
            gap_y = random.randint(PIPE_MIN_GAP_Y + 20, WINDOW_HEIGHT - self.current_pipe_gap - 40)
            p = PipePair(spawn_x, gap_y, self.current_pipe_gap, int(WINDOW_WIDTH * 0.12), WINDOW_HEIGHT)
            self.pipes.append(p)
            self.add_widget(p)

        if self._update_event:
            Clock.unschedule(self._update_event)
        self._update_event = Clock.schedule_interval(self._update, 1.0 / 60.0)
        print("[Game] Started")

    def clear_pipes(self):
        for p in list(self.pipes):
            try:
                self.remove_widget(p)
            except:
                pass
        self.pipes = []

    def end_game(self):
        self.game_over = True
        self.running = False
        if self._update_event:
            Clock.unschedule(self._update_event)
            self._update_event = None
        self._game_over_label = Label(text=f"Game Over!\nScore: {self.score}", font_size=32,
                                      halign='center', valign='middle',
                                      size_hint=(None, None), size=(300, 120),
                                      pos=(WINDOW_WIDTH / 2 - 150, WINDOW_HEIGHT / 2 - 60),
                                      color=(1, 0.3, 0.3, 1))
        self.add_widget(self._game_over_label)
        self.start_button.text = "Restart"
        self.add_widget(self.start_button)
        print("[Game] Game Over. Score:", self.score)

    def _apply_difficulty(self):
        if self.score < 30:
            self.current_pipe_speed = EASY['PIPE_SPEED']
            self.current_pipe_gap = EASY['PIPE_GAP']
            self.current_spawn_interval = EASY['PIPE_SPAWN_INTERVAL']
            self.initial_spacing_mult = EASY['INITIAL_SPACING_MULT']
        else:
            extra = max(0, self.score - 30)
            ramp_factor = min(1.0, extra / 50.0)
            self.current_pipe_speed = HARD['PIPE_SPEED'] + RAMP_MAX_ADDITIONAL_SPEED * ramp_factor
            self.current_pipe_gap = int(max(60, HARD['PIPE_GAP'] - RAMP_MAX_GAP_REDUCTION * ramp_factor))
            self.current_spawn_interval = max(0.9, HARD['PIPE_SPAWN_INTERVAL'] - 0.8 * ramp_factor)
            self.initial_spacing_mult = HARD['INITIAL_SPACING_MULT']

    def _update(self, dt):
        if not self.running or self.game_over:
            return

        self._apply_difficulty()
        self.bird.physics_step(dt)

        if self.bird.y <= 0:
            self.bird.y = 0
            self.end_game()
            return
        if self.bird.top >= WINDOW_HEIGHT:
            self.bird.y = WINDOW_HEIGHT - self.bird.height
            self.end_game()
            return

        dx = -self.current_pipe_speed * dt
        for p in list(self.pipes):
            p.move(dx)
            if p.right < -50:
                try:
                    self.remove_widget(p)
                except:
                    pass
                if p in self.pipes:
                    self.pipes.remove(p)

        self._time_since_last_spawn += dt
        if self._time_since_last_spawn >= self.current_spawn_interval:
            rightmost = max([p.x for p in self.pipes]) if self.pipes else 0
            spawn_x = max(WINDOW_WIDTH + 20, rightmost + int(WINDOW_WIDTH * 0.7))
            gap_y = random.randint(PIPE_MIN_GAP_Y + 10, WINDOW_HEIGHT - self.current_pipe_gap - 30)
            new_pipe = PipePair(spawn_x, gap_y, self.current_pipe_gap, int(WINDOW_WIDTH * 0.12), WINDOW_HEIGHT)
            self.pipes.append(new_pipe)
            self.add_widget(new_pipe)
            self._time_since_last_spawn = 0.0

        # secret bot
        if self.autoplay:
            self._autoflap_logic()

        bx, by, bw, bh = self.bird.x, self.bird.y, self.bird.width, self.bird.height
        for p in self.pipes:
            if p.collides_with(bx, by, bw, bh):
                self.end_game()
                return
            if not p.scored and p.right < self.bird.x:
                p.scored = True
                self.score += 1
                self.score_label.text = f"Score: {self.score}"

    def on_parent(self, widget, parent):
        if parent is None:
            if self._update_event:
                Clock.unschedule(self._update_event)
            Window.unbind(on_key_down=self._on_key_down)

# -------------------------
# Splash screen (6 seconds)
# -------------------------
class SplashScreen(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            Color(0, 0, 0, 1)
            self.rect = Rectangle(pos=(0, 0), size=Window.size)
        self.label = Label(
            text="THIS GAME IS DEVELOPED AND TESTED BY\nMR ABHIJITH KUMAR",
            halign='center', valign='middle', color=(1, 1, 1, 1),
            font_size=28, size_hint=(None, None), size=(WINDOW_WIDTH, 120),
            pos=(0, WINDOW_HEIGHT / 2 - 60)
        )
        self.label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.add_widget(self.label)

# -------------------------
# App
# -------------------------
class FlappyFaceApp(App):
    def build(self):
        # prepare game and splash
        self.game_widget = FlappyGame()
        self.splash = SplashScreen()
        # show splash for 6 seconds
        Clock.schedule_once(self._start_game_after_splash, 6.0)
        return self.splash

    def _start_game_after_splash(self, dt):
        self.root.clear_widgets()
        self.root.add_widget(self.game_widget)
        self.game_widget.start_game(None)

if __name__ == '__main__':
    FlappyFaceApp().run()
