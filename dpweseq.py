# dpweseq.py

# DONE
#  - separate track structures
#  - per-track record-ready radio button
#  - playback non-record tracks during record
#  - undo/redo
#  - "overwrite-on-record" - delete notes within newly-recorded range - currently everything after playhead
#  - Save & Load of sequences
#  - mute track button
#  - metronome
# TODO
#  - playback routing: Send MIDI events rather than Synth.note_* events?  As an option?
#  - add metronome on/off, controls for BPM and meter
# ISSUES
#  - when two tracks play to the same synth, the note-offs can cancel each other's overlapping notes
#  - Toggling while playing doesn't work (we'd need to reschedule everything)
#  - Moving playhead while playing doesn't work (we'd need to reschedule everything)

import synth, tulip, midi, amy
import ui
import json  # for load/save

app = None
(screen_width, screen_height) = tulip.screen_size()

midi_channels = [None] * 4
all_active_channels = set()

def app_hwm(tick):
    """Set the app time high water mark."""
    global app
    if(tick > app.last_ms): app.last_ms = tick


def _ms_to_x(ms):
    global app
    return int((ms - app.x_offset_ms) / app.ms_per_px)

# dpwe to make this more real. 
class SeqNote:

    def __init__(self, note, vel, tick, channel, duration=None):
        global all_active_channels
        self.channel = channel
        all_active_channels.add(channel)
        self.note = note
        self.vel = vel
        self.on_tick = tick
        if duration is None:
            self.off_tick = None
        else:
            self.off_tick = self.on_tick + duration

    def set_end(self, off_tick):
        self.off_tick = off_tick
        
    def draw(self, base_x=0, base_y=60, color=93):
        global app
        # We allow specifying the color not least to support erasing with the background color.
        # only draw if fits in view
        if(self.on_tick >= app.x_offset_ms and self.on_tick < app.x_offset_ms + (app.ms_per_px*screen_width)):
            # handle midi notes 30-90
            if(self.note > 29 and self.note < 90):
                # height of channel is 120
                cy = 120 - ((self.note - 29) * 2)
                cx_on = _ms_to_x(self.on_tick)
                if self.off_tick is not None:
                    cx_off = _ms_to_x(self.off_tick)
                else:
                    # Note is still down - draw bar up to cursor
                    cx_off = _ms_to_x(app.playhead_ms)
                tulip.bg_rect(base_x + cx_on, base_y + cy, cx_off - cx_on + 2, 2, color, 1)

    def schedule(self, note_on_fn, note_off_fn=None, offset=0):
        global app
        if note_on_fn:
           note_on_fn(self.note, self.vel / 127, time=self.on_tick - offset)
           if self.off_tick is not None:
               if note_off_fn:
                   note_off_fn(self.note, time=self.off_tick - offset)
               else:
                   note_on_fn(self.note, 0, time=self.off_tick - offset)
                
    def as_list(self):
        """Return list of scalars, for saving as json."""
        duration = self.off_tick - self.on_tick if self.off_tick is not None else None
        return self.on_tick, duration, self.channel, self.note, self.vel

    @staticmethod
    def from_list(params):
        """Factory for a SeqNote from list of params as returned by as_list()."""
        on_tick, duration, channel, note, vel = params
        return SeqNote(note=note, vel=vel, channel=channel, tick=on_tick, duration=duration)


class Track:
    """A single track of the sequencer."""

    def __init__(self, index, x, y, w=0, h=0, fg_color=93, bg_color=32, note_on_fn=None, note_off_fn=None):
        global screen_width, screen_height
        self.index = index
        self.x = x
        self.y = y
        self.w = w if w else screen_width - x
        self.h = h if h else screen_height // 5
        self.fg_color = fg_color
        self.bg_color = bg_color
        self.note_on_fn = note_on_fn
        self.note_off_fn = note_off_fn
        self.notes = []
        self.saved_notes = []
        self.live_notes_dict = {}
        # Setup sprite
        tulip.sprite_register(index, 0, 1, self.h)
        tulip.sprite_on(index)
        tulip.sprite_move(index, self.x, self.y)
        # Setup record button
        self.rec_button = tulip.UIButton(text="R", bg_color=0x49, fg_color=255, callback=self.rec_pushed)
        app.add(self.rec_button, x=self.x - 80, y=self.y - 0)
        self.rec_live = False
        # Setup mute button
        self.mute_button = tulip.UIButton(text="M", bg_color=0x49, fg_color=255, callback=self.mute_pushed)
        app.add(self.mute_button, x=self.x - 80, y=self.y + 60)
        self.muted = False

    def rec_pushed(self, val):
        global app
        self.set_rec(not self.rec_live)
        if self.rec_live:
            # If this record was selected, deselect all other recs.
            for track in app.tracks:
                if track != self:
                    track.set_rec(False)

    def set_rec(self, val):
        global app
        self.rec_live = val
        color = 0xc0 if val else 0x49
        self.rec_button.button.set_style_bg_color(ui.pal_to_lv(color), ui.lv.PART.MAIN)
        if val:
            app.current_track = self
        elif app.current_track == self:
            app.current_track = None

    def mute_pushed(self, val):
        self.set_muted(not self.muted)

    def set_muted(self, val):
        self.muted = val
        color = 0xD4 if self.muted else 0x49
        self.mute_button.button.set_style_bg_color(ui.pal_to_lv(color), ui.lv.PART.MAIN)

    def clear_notes(self, clear_from_ms=0):
        """Save current notes, clear notes, redraw."""
        if self.notes:
            self.saved_notes = self.notes
            add_undo_object(self)
        # Keep notes that start before clear_from_ms
        self.notes = [n for n in self.notes if n.on_tick < clear_from_ms]
        self.draw()

    def undo(self):
        """Restore the saved_notes, swap with current notes."""
        self.notes, self.saved_notes = self.saved_notes, self.notes
        self.draw()

    def redo(self):
        """Redo - is the same as undo, since we're swapping one history."""
        self.undo()

    def move_playhead(self, time_ms):
        global app
        x = self.x + _ms_to_x(time_ms)

        # Extend non-terminated notes to playhead.
        self.draw_live_notes()

        tulip.sprite_move(self.index, x, self.y)

    def draw(self):
        tulip.bg_rect(self.x, self.y, self.w, self.h, self.bg_color, 1)
        for note in self.notes:
            note.draw(base_x=self.x, base_y=self.y, color=self.fg_color)

    def schedule_notes(self, offset_ms=0):
        if self.muted:
            return
        for note in self.notes:
            # Only schedule things ahead of the playhead when we start
            if(note.on_tick > offset_ms):
                note.schedule(offset=offset_ms, note_on_fn=self.note_on_fn, note_off_fn=self.note_off_fn)

    def consume_midi_event(self, message, tick):
        global app
        method = message[0] & 0xF0
        channel = (message[0] & 0x0F) + 1
        control = message[1]
        value = message[2] if len(message) > 2 else None
        if(method == 0x90): # note on
            note = control
            seq_note = SeqNote(note, value, tick, channel)
            self.live_notes_dict[(channel, note)] = seq_note
            self.notes.append(seq_note)
            app_hwm(tick)            
        if(method == 0x80): #note off
            note = control
            if (channel, note) in self.live_notes_dict:
                seq_note = self.live_notes_dict[(channel, note)]
                seq_note.set_end(tick)
                del self.live_notes_dict[(channel, note)]
                app_hwm(tick)
            else:
                print('unexpected note_off on channel, note', channel, note)
       
    def draw_live_notes(self):
        for note in self.live_notes_dict.values():
            note.draw(base_x=self.x, base_y=self.y, color=self.fg_color)
        
    def stop_live_notes(self, tick):
        for note in self.live_notes_dict.values():
            note.set_end(tick)
        self.live_notes_dict = {}

    def x_to_ms(self, x):
        """Map a touch x back to time in ms."""
        global app
        return (x - self.x) * app.ms_per_px + app.x_offset_ms

    def load_notes_from_list(self, notes):
        self.clear_notes()  # Allows undo
        self.notes = [SeqNote.from_list(n) for n in notes]
        self.draw()

    def get_notes_as_list(self):
        return [n.as_list() for n in self.notes]


# Metronome plays during record
class Metronome:

    def __init__(self, osc=amy.AMY_OSCS - 1, period=48, meter=4):
        self.osc = osc
        self.period = period
        self.meter = meter  # High beep every this many
        self.tempo = 108
        amy.send(osc=self.osc, wave=amy.SINE, bp0='10,1,10,1,10,0,0,0')

    def ms_to_tick(self, ms):
        ticks_per_beat = 48
        ms_per_tempo_tick = 60000 / self.tempo / ticks_per_beat
        return round(ms / ms_per_tempo_tick)

    def start(self, offset_ms=0):
        total_period = self.period * self.meter
        # Figure where to play downbeat relative to playhead offset.
        offset = -self.ms_to_tick(offset_ms)
        amy.send(osc=self.osc, vel=1, note=72, sequence='%d,%d,0' % ((offset) % total_period,  total_period))
        for i in range(1, self.meter):
              amy.send(osc=self.osc, vel=1, note=60, sequence='%d,%d,%d' % (
                  (offset + i * self.period) % total_period, total_period, i))

    def stop(self):
        # Clear each of the sequencer loops.
        for i in range(self.meter):
            amy.send(osc=self.osc, sequence='0,0,%d' % i)
        #amy.send(reset=amy.RESET_SEQUENCER)


def quit(app):
    pass

# Got a midi message. parse it and store it
def midi_received(message):
    global app
    if(app.recording):
        tick = tulip.amy_ticks_ms() + app.offset_ms
        if app.current_track is not None:
            app.current_track.consume_midi_event(message, tick)
            update_seq_position_bar()


def move_playhead():
    global app
    app.playhead_ms = tulip.amy_ticks_ms() + app.offset_ms
    for track in app.tracks:
        track.move_playhead(app.playhead_ms)


# called every frane
def frame_cb(x):
    global app
    if(app.playing or app.recording):
        move_playhead()
        #if(app.playing and app.playhead_ms > app.last_ms):
        #    app.playing = False

def touch_cb(up):
    global app
    (x,y,_,_,_,_) = tulip.touch()
    # is this a click on the sequence or the position bar?
    update = False
    top_of_tracks = app.tracks[0].y
    bottom_of_tracks = app.tracks[-1].y + app.tracks[-1].h
    if y >= top_of_tracks and y < bottom_of_tracks and x >= app.tracks[0].x:
        # Within the track stripes, move the playhead.
        app.offset_ms = app.tracks[0].x_to_ms(x)
        update = True
    if y > bottom_of_tracks: # position bar
        pos_ms = app.last_ms * (x / screen_width)
        # only move view if this click is outside of view
        if(not (pos_ms >= app.x_offset_ms and pos_ms < app.x_offset_ms + (app.ms_per_px*screen_width))):
            app.offset_ms = pos_ms
            app.x_offset_ms = pos_ms 
            app.playhead_ms = pos_ms
            draw()
            update = True
    if(update):
        # Reset time and also upcoming events
        amy.send(reset=amy.RESET_TIMEBASE + amy.RESET_EVENTS)
        move_playhead()
        if(app.playing): # reschedule events if playing
            for track in app.tracks:
                track.schedule_notes(app.offset_ms)


def rec_pushed(x):
    global app
    if app.playing or app.recording:
        # Pressing record during play/record does stop.
        stop_pushed(x)
    else:
        # Start recording
        amy.send(reset=amy.RESET_TIMEBASE)
        app.playing = False
        app.recording = True
        # We're about to record, clear the notes in the record-to track
        if app.current_track:
            app.current_track.clear_notes(app.playhead_ms)
            # start recording from playhead position
        app.offset_ms = app.playhead_ms
        # Set the other tracks playing
        for track in app.tracks:
            if track != app.current_track:
                track.schedule_notes(app.offset_ms)
                # Start the metronome
        app.metronome.start(app.offset_ms)


def play_pushed(x):
    global app
    if app.playing or app.recording:
        # Pressing play during rec/play does stop.
        stop_pushed(x)
    else:
        # Start playing
        amy.send(reset=amy.RESET_TIMEBASE)
        app.recording = False
        app.playing = True
        app.offset_ms = app.playhead_ms
        for track in app.tracks:
            track.schedule_notes(app.offset_ms)

def rtz_pushed(x):
    global app
    if app.playing or app.recording:
        # Pressing play during rec/play does stop.
        stop_pushed(x)
    amy.send(reset=amy.RESET_TIMEBASE)
    app.offset_ms = 0
    app.x_offset_ms = 0
    app.playhead_ms = 0
    move_playhead()
    draw()

def stop_pushed(x):
    global app, all_active_channels
    app.playing = False
    app.recording = False
    # Stop any current-sounding notes.
    tick = tulip.amy_ticks_ms() + app.offset_ms
    for track in app.tracks:
        track.stop_live_notes(tick)
    # clear any AMY messages in the queue / currently sounding.
    amy.send(reset=amy.RESET_EVENTS)
    amy.send(reset=amy.RESET_ALL_NOTES)
    # Stop the metronome
    app.metronome.stop()

def save_pushed(x):
    global app
    all_notes = {}
    num_notes = 0
    for index, track in enumerate(app.tracks):
        all_notes[index] = track.get_notes_as_list()
        num_notes += len(all_notes[index])
    filename = 'dpweseq_saved.json'
    with open(filename, 'w') as f:
        json.dump(all_notes, f)
    #print(num_notes, 'notes saved to', filename)

def load_pushed(x):
    global app
    filename = 'dpweseq_saved.json'
    with open(filename, 'r') as f:
        all_notes = json.load(f)
    num_notes = 0
    for index, notes in all_notes.items():
        app.tracks[int(index)].load_notes_from_list(notes)
        num_notes += len(notes)
    #print(num_notes, 'notes read from', filename)
    draw()

def zoom_changed(x):
    global app
    val = x.get_target_obj().get_value()
    # set zoom where 0 (left) = 100 ms_per_px and 100 (right) = 5 ms_per_px 
    app.ms_per_px = max((100 - val), 5)
    draw()

def activate(app):
    setup_playhead_sprites()
    draw()
    midi.add_callback(midi_received)
    tulip.touch_callback(touch_cb)
    tulip.frame_callback(frame_cb)

def deactivate(app):
    midi.remove_callback(midi_received)
    tulip.touch_callback()

def setup_playhead_sprites():
    bitmap = bytes([0x55, 0x55, 159] * 40) # just a light blue dotted line (0x55 is alpha), 120px hight, 1 px wide
    tulip.sprite_bitmap(bitmap, 0)

def update_seq_position_bar():
    # Draw a box on the bottom to show zoom position
    ms_per_screen = app.ms_per_px * screen_width
    if(app.last_ms > ms_per_screen): 
        screen_use_px = int((ms_per_screen / app.last_ms) * screen_width)
        seq_position_px = int((app.x_offset_ms / app.last_ms) * screen_width)
    else:
        screen_use_px= screen_width
        seq_position_px = 0
    tulip.bg_rect(0, 580, screen_width, 20, 109, 1)
    tulip.bg_rect(seq_position_px, 580, screen_use_px, 20, 165, 1)

# Redraw everything
def init_tracks():
    global screen_width, screen_height
    channel_bg_colors = [32, 5, 4, 33]
    track_x = 70
    track_y = 60
    track_w = screen_width - track_x
    track_h = screen_height // 5
    channel = 1  # For now, all tracks drive the Synth on MIDI channel 1.
    for i in range(4):
        app.tracks.append(
            Track(
                i,
                x=track_x,
                y=track_y + (track_h + 10) * i,
                w=track_w,
                h=track_h,
                bg_color=channel_bg_colors[i],
                note_on_fn=midi.config.synth_per_channel[channel].note_on,
                note_off_fn=midi.config.synth_per_channel[channel].note_off,
            )
        )

def draw():
    global app
    for track in app.tracks:
        track.draw()

    update_seq_position_bar()


# Undo stack is a list of objects that provide undo() and redo() methods.
undo_stack = []
# Which item is the next one to undo (or just beyond the next one to redo).
undo_position = 0

def undo_pushed(x):
    global app, undo_stack, undo_position
    if undo_position < len(undo_stack):
        undo_stack[undo_position].undo()
        undo_position += 1

def redo_pushed(x):
    global app, undo_stack, undo_position
    if undo_position > 0:
        undo_position -= 1
        undo_stack[undo_position].redo()

def add_undo_object(object):
    """Add a new object to the top of the undo stack."""
    global undo_stack, undo_position
    undo_stack = [object] + undo_stack[undo_position:]
    undo_position = 0

# from lv_binding_micropython_tulip/lvgl/src/font/lv_symbol_def.h
#LV_SYMBOL_PLAY = "\xEF\x81\x8B"

def run(screen):
    global app
    app = screen
    # Since we're using sprites, BG drawing and scrolling, use "game mode"
    app.game = True

    # Where in ms of the sequence the left side of the screen is
    app.x_offset_ms = 0
    # Where the playhead is currently in the sequence, moves during recording/playback
    app.playhead_ms = 0
    # Where the record/play started from, as an offset in ms
    app.offset_ms = 0
    # The latest note ms
    app.last_ms = 0

    app.recording = False
    app.playing = False
    app.tracks = []
    app.activate_callback = activate
    app.quit_callback = quit
    app.deactivate_callback = deactivate
    app.add(tulip.UIButton(text="O",  bg_color=96, fg_color=255, callback=rec_pushed), x=0, y=0)
    app.add(tulip.UIButton(text="|>", bg_color=48, fg_color=255, callback=play_pushed))
    app.add(tulip.UIButton(text="|<", bg_color=252, fg_color=0, callback=rtz_pushed))
    #app.add(tulip.UIButton(text="Stop", bg_color=237, fg_color=0, callback=stop_pushed))
    app.add(tulip.UIButton(text="Lo", bg_color=10, fg_color=0, callback=load_pushed))
    app.add(tulip.UIButton(text="Sa", bg_color=18, fg_color=0, callback=save_pushed))
    app.add(tulip.UIButton(text="Un", bg_color=102, fg_color=0, callback=undo_pushed))
    app.add(tulip.UIButton(text="Re", bg_color=134, fg_color=0, callback=redo_pushed))
    app.add(tulip.UISlider(w=200, val=70, bar_color=74, handle_color=208, handle_radius=25, callback=zoom_changed))
    app.ms_per_px = 30 

    init_tracks()
    app.current_track = None

    # Now make track 0 the current record-to track.
    app.tracks[0].set_rec(True)

    app.metronome = Metronome(period=48, meter=4)

    app.present()


if __name__ == '__main__':
    run(tulip.UIScreen())
