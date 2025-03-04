# dpweseq.py

# DONE
#  - separate track structures
#  - per-track record-ready radio button
#  - playback non-record tracks during record
# TODO
#  - "overwrite-on-record" - delete notes that begin within newly-recorded range
#  - Per-track "record/insert/playback/mute" switch (currently just record)
#  - playback routing: Send MIDI events rather than Synth.note_* events?  As an option?
#  - Save & Load of sequences

import synth, tulip, midi, amy
import ui
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

    def __init__(self, note, vel, tick, channel):
        global all_active_channels
        self.channel = channel
        all_active_channels.add(channel)
        self.note = note
        self.vel = vel
        self.on_tick = tick
        self.off_tick = None
        
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

    def schedule(self, offset=0):
        global app
        midi.config.synth_per_channel[self.channel].note_on(self.note, self.vel, time=self.on_tick - offset)
        if self.off_tick is not None:
            midi.config.synth_per_channel[self.channel].note_off(self.note, time=self.off_tick - offset)


class Track:
    """A single track of the sequencer."""

    def __init__(self, index, x, y, w=0, h=0, fg_color=93, bg_color=32):
        global screen_width, screen_height
        self.index = index
        self.x = x
        self.y = y
        self.w = w if w else screen_width - x
        self.h = h if h else screen_height // 5
        self.fg_color = fg_color
        self.bg_color = bg_color
        self.notes = []
        self.live_notes_dict = {}
        # Setup sprite
        tulip.sprite_register(index, 0, 1, self.h)
        tulip.sprite_on(index)
        tulip.sprite_move(index, self.x, self.y)
        # Setup record button
        self.rec_button = tulip.UIButton(text="R", bg_color=bg_color, fg_color=255, callback=self.rec_pushed)
        app.add(self.rec_button, x=self.x - 80, y=self.y + 20)
        self.rec_live = False

    def set_rec(self, val):
        global app
        self.rec_live = val
        color = self.bg_color + self.rec_live * 73
        self.rec_button.button.set_style_bg_color(ui.pal_to_lv(color), ui.lv.PART.MAIN)
        if val:
            app.current_track = self
        elif app.current_track == self:
            app.current_track = None

    def rec_pushed(self, val):
        global app
        self.set_rec(not self.rec_live)
        # If this record was selected, deselect all other recs.
        if self.rec_live:
            for track in app.tracks:
                if track != self:
                    track.set_rec(False)

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
        for note in self.notes:
            # Only schedule things ahead of the playhead when we start
            if(note.on_tick > offset_ms):
                note.schedule(offset=offset_ms)

    def consume_midi_event(self, message, tick):
        global app
        method = message[0] & 0xF0
        channel = (message[0] & 0x0F) + 1
        control = message[1]
        value = message[2] if len(message) > 2 else None
        if(method == 0x90): # note on
            note = control
            seq_note = SeqNote(note, value/127., tick, channel)
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

    def set_notes(self, notes):
        self.notes = notes

    def get_notes(self):
        return self.notes


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
    if(app.playing and app.playhead_ms > app.last_ms):
        app.playing = False

def touch_cb(up):
    global app
    (x,y,_,_,_,_) = tulip.touch()
    # is this a click on the sequence or the position bar
    update = False
    if(y >= app.tracks[0].y and y < app.tracks[-1].y + app.tracks[-1].h and x >= app.tracks[0].x):
        app.offset_ms = app.tracks[0].x_to_ms(x)
        update = True
    if(y>570): # position bar
        pos_ms = app.last_ms*(x/screen_width)
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
    if(not app.recording):
        amy.send(reset=amy.RESET_TIMEBASE)
        app.playing = False
        app.recording = True
        # start recording from playhead position
        app.offset_ms = app.playhead_ms
        # Set the other tracks playing
        for track in app.tracks:
            if track != app.current_track:
                track.schedule_notes(app.offset_ms)


def play_pushed(x):
    global app
    if app.recording:
        print('play pressed during recording: ignored')
    elif(not app.playing):
        amy.send(reset=amy.RESET_TIMEBASE)
        app.recording = False
        app.playing = True
        app.offset_ms = app.playhead_ms
        for track in app.tracks:
            track.schedule_notes(app.offset_ms)

def rw_pushed(x):
    global app
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
        screen_use_px = int((ms_per_screen / app.last_ms)*screen_width)
        seq_position_px = int((app.x_offset_ms / app.last_ms)*screen_width)
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
    for i in range(4):
        app.tracks.append(
            Track(i, x=track_x, y=track_y + (track_h + 10) * i, w=track_w, h=track_h, bg_color=channel_bg_colors[i])
        )

def draw():
    global app
    for track in app.tracks:
        track.draw()

    update_seq_position_bar()


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
    app.add(tulip.UIButton(text="Rec",  bg_color=96, fg_color=255, callback=rec_pushed), x=0, y=0)
    app.add(tulip.UIButton(text="Play", bg_color=48, fg_color=255, callback=play_pushed))
    app.add(tulip.UIButton(text="Rewind", bg_color=252, fg_color=0, callback=rw_pushed))
    app.add(tulip.UIButton(text="Stop", bg_color=237, fg_color=0, callback=stop_pushed))
    app.add(tulip.UISlider(w=200, val=70, bar_color=74, handle_color=208, handle_radius=25, callback=zoom_changed))
    app.ms_per_px = 30 

    init_tracks()
    app.current_track = None

    # Now make track 0 the current record-to track.
    app.tracks[0].set_rec(True)

    app.present()


if __name__ == '__main__':
    run(tulip.UIScreen())

