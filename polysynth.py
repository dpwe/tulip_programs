"""
Polyphonic synthesizer driven by midi events.

This file includes:

OscSource - an object that manages the allocation of amy oscillators.

NoteBase - a base class that handles obtaining oscillators from OscSource

SimpleNote - a derived class that implements a simple filtered sawtooth voice.

FMNote - a derived class that uses the built-in DX7 FM patches as notes.

midi_event_cb - a callback that starts and stops notes in response to midi
                events.

Usage: Connect a MIDI keyboard to either the Tulip MIDI input, or via USB to
the Tulip keyboard connector.  (On Tulip Desktop Mac, just connect a MIDI-USB
keyboard).  Run the script, then the notes are dispatched in the background,
via the midi callback hook.

>>> execfile("polysynth.py")
>>> set_patch(10)  # E.PIANO 1 - see amy/src/fm.h

Releases:
2023-07-16 Supporting control inputs from Oxygen49 MIDI keyboard.
           Pitch bend works.
           Set SYNTH_TYPE='juno' for WIP analog synth emulation, with sliders
           for ADSR for amplitude and filter, LFO rate, and knobs for
           filter freq, filter Q, and pitch LFO depth.  However, something
           weird is happening with release, such that the notes tend to
           retrigger or something if one envelope has a longer release than
           the other.

2023-07-10 Pseudo coroutines via the "rescind queue" returns oscs a short
           while (Note.release_time) after their note off, so held notes won't
           be stolen if later short notes have ended.
"""

import math
import time
#import queue
from collections import namedtuple

try:
    import amy
    amy.live()
except:
    amy = alles
    alles.chorus(1)

# Optional monkeypatch of send() method to diagnose exactly what is being sent.
def amy_send_patch(osc=0, wave=-1, patch=-1, note=-1, vel=-1, amp=-1, freq=-1, duty=-1, feedback=-1, timestamp=None, reset=-1, phase=-1, pan=-1, \
        client=-1, retries=1, volume=-1, filter_freq = -1, resonance = -1, bp0="", bp1="", bp2="", bp0_target=-1, bp1_target=-1, bp2_target=-1, mod_target=-1, \
        debug=-1, mod_source=-1, eq_l = -1, eq_m = -1, eq_h = -1, filter_type= -1, algorithm=-1, ratio = -1, latency_ms = -1, algo_source=None, chorus_level=-1, \
        chorus_delay=-1, reverb_level=-1, reverb_liveness=-1, reverb_damping=-1, reverb_xover=-1):
    print("amy_send:", osc, wave, patch, note, vel, amp, freq, filter_freq, resonance, bp0, bp1)
    orig_amy_send(osc=osc, wave=wave, patch=patch, note=note, vel=vel, amp=amp, freq=freq, duty=duty, feedback=feedback, timestamp=timestamp, reset=reset, phase=phase, pan=pan, \
                  client=client, retries=retries, volume=volume, filter_freq=filter_freq, resonance=resonance, bp0=bp0, bp1=bp1, bp2=bp2, bp0_target=bp0_target, bp1_target=bp1_target, bp2_target=bp2_target, mod_target=mod_target, \
                  debug=debug, mod_source=mod_source, eq_l=eq_l, eq_m=eq_m, eq_h=eq_h, filter_type=filter_type, algorithm=algorithm, ratio=ratio, latency_ms=latency_ms, algo_source=algo_source, chorus_level=chorus_level, \
                  chorus_delay=chorus_delay, reverb_level=reverb_level, reverb_liveness=reverb_liveness, reverb_damping=reverb_damping, reverb_xover=reverb_xover)

# Apply the monkeypatch?
#orig_amy_send = amy.send
#amy.send = amy_send_patch


# Micropython collections.deque does not support remove.
class Queue:
    def __init__(self, maxsize=64):
        self.maxsize = maxsize + 1
        self.queue = [None] * self.maxsize
        self.head = 0
        self.tail = 0

    def _next(self, pointer):
        """Incrementing a cicular buffer pointer."""
        return (pointer + 1) % self.maxsize
        
    def _prev(self, pointer):
        """Decrementing a cicular buffer pointer."""
        return (pointer + self.maxsize - 1) % self.maxsize
        
    def put(self, item):
        self.queue[self.tail] = item
        self.tail = self._next(self.tail)
        if self.tail == self.head:
            # Wrap around
            self.head = self._next(self.head)
            print("queue: dropped oldest item")

    def _delete_at(self, pointer):
        """Remove the value at queue[pointer], and close up the rest."""
        if self.tail > pointer:
            self.queue[pointer : self.tail - 1] = (
                self.queue[pointer + 1 : self.tail])
            self.tail = self._prev(self.tail)
        elif self.tail < pointer:
            self.queue[pointer : -1] = self.queue[pointer + 1:]
            self.queue[-1] = self.queue[0]
            self.tail = self._prev(self.tail)
        else:
            raise ValueError('pointer at tail???')

    def remove(self, value):
        """Remove first occurrence of value from queue."""
        pointer = self.head
        while pointer != self.tail:
            if self.queue[pointer] == value:
                self._delete_at(pointer)
                return
            pointer = self._next(pointer)
        # Fell through, value wasn't found.
        raise ValueError
            
    def empty(self):
        return self.head == self.tail

    def full(self):
        return self.head == self._next(self.tail)

    def qsize(self):
        return (self.tail - self.head + self.maxsize) % self.maxsize

    def get(self):
        if self.empty():
            # get() on empty queue.
            raise ValueError
        value = self.queue[self.head]
        self.head = self._next(self.head)
        return value

    def __repr__(self):
        result = []
        p = self.head
        while p != self.tail:
            result.append(self.queue[p])
            p = self._next(p)
        return ("Queue(maxsize=%d) [" % (self.maxsize - 1)
                + (", ".join(str(s) for s in result))
                + "]")


class PriorityQueue:
    def __init__(self):
        self.pairs = []
    
    def insert_at_priority(self, priority, value):
        num_pairs = len(self.pairs)
        for i in range(num_pairs):
            pair_priority = self.pairs[i][0]
            if pair_priority > priority:
                # Insert before this item
                self.pairs = (
                    self.pairs[:i] + [(priority, value)] + self.pairs[i:])
                return
        # If we fall through, put it on the end
        self.pairs.append((priority, value))

    def peek(self):
        return self.pairs[0]

    def get(self):
        pair = self.pairs[0]
        del self.pairs[0]
        return pair

    def remove(self, value):
        for index, pair in enumerate(self.pairs):
            if pair[1] == value:
                del self.pairs[index]
                return
        # Didn't find it
        raise ValueError

    def qsize(self):
        return len(self.pairs)

    def empty(self):
        return self.qsize() == 0
        

def now():
    """Timebase, in seconds."""
    return amy.millis() / 1000

# The return type of OscSource
OscSet = namedtuple("OscSet", "oscs bank rescind_fn")


class OscSource:
    """Class that manages allocating oscillators arranged into banks,
       including stealing old allocs when we run out."""
    TOTAL_OSCS = 64 # 48  # 64
    NUM_USABLE_OSCS = 62
    OSC_BLOCKING = 32  # Don't let sets of oscs straddle this.

    def __init__(self):
        self.available_oscs_by_bank = []
        for bottom_osc in range(0, self.NUM_USABLE_OSCS, self.OSC_BLOCKING):
            self.available_oscs_by_bank.append(
                list(range(bottom_osc, min(bottom_osc + self.OSC_BLOCKING,
                                           self.NUM_USABLE_OSCS))))
        self.allocated_oscset_queues_by_bank = []
        num_banks = len(self.available_oscs_by_bank)
        self.bank_stealing_queue = Queue(num_banks)
        for bank in range(num_banks):
            self.bank_stealing_queue.put(bank)
            # Allocated oscset queues must be long enough to hold the largest
            # number of allocs possible == #oscs in bank.  However, allocs
            # of > 1 osc will make actual max likely lower.
            self.allocated_oscset_queues_by_bank.append(
                Queue(len(self.available_oscs_by_bank[bank])))
        # To store oscsets to be returned in the future.
        self.rescind_queue = PriorityQueue()

    def choose_bank(self):
        """Return the bank with the most oscillators."""
        best_bank = -1
        most_oscs = -1
        for bank_num, bank_oscs in enumerate(self.available_oscs_by_bank):
            num_oscs = len(bank_oscs)
            if num_oscs > most_oscs:
                best_bank = bank_num
                most_oscs = num_oscs
        return best_bank

    def rescind(self, oscset):
        if oscset.rescind_fn:
            oscset.rescind_fn()
        bank = oscset.bank
        #self.available_oscs_by_bank[bank].extend(oscset.oscs)
        # Return these oscillators to the top of this list.
        # This ensures that blocks of oscillators remain contiguous
        # which is important for the 8/9 oscs needed for wave.ALGO.
        self.available_oscs_by_bank[bank] = (
            oscset.oscs + self.available_oscs_by_bank[bank])

    def steal_from_bank(self, bank):
        """Steal the oldest alloc in the indicated bank."""
        oscset = self.allocated_oscset_queues_by_bank[bank].get()
        assert oscset.bank == bank
        alen = self.allocated_oscset_queues_by_bank[bank].qsize()
        print(f"steal: bank {bank} alloc_oscset_len {alen}")
        self.rescind(oscset)
        # Maybe it has already been scheduled for note off?
        try:
            self.rescind_queue.remove(oscset)
        except:
            pass
    
    def get_oscs(self, num_oscs, rescind_fn=None):
        """Public method to obtain new oscillators.
           <rescind_fn> will be called when alloc is about to be stolen."""
        # Recover any unneeded oscs.
        self.process_rescind_queue()
        # Choose which bank to allocate from.
        best_bank = self.choose_bank()
        available_oscs = self.available_oscs_by_bank[best_bank]
        if len(available_oscs) < num_oscs:
            # Even best bank has too few slots.
            # Steal some oscs from the next stealing bank
            best_bank = self.bank_stealing_queue.get()
            self.bank_stealing_queue.put(best_bank)
            available_oscs = self.available_oscs_by_bank[best_bank]
            while len(available_oscs) < num_oscs:
                self.steal_from_bank(best_bank)
                # available_oscs_by_bank may have been replaced, refresh.
                available_oscs = self.available_oscs_by_bank[best_bank]
        if len(available_oscs) >= num_oscs:
            oscs = available_oscs[:num_oscs]
            self.available_oscs_by_bank[best_bank] = available_oscs[num_oscs:]
            oscset = OscSet(oscs=oscs, bank=best_bank, rescind_fn=rescind_fn)
            self.allocated_oscset_queues_by_bank[best_bank].put(oscset)
            alen = self.allocated_oscset_queues_by_bank[best_bank].qsize()
            return oscset

    def process_rescind_queue(self):
        t = now()
        while not self.rescind_queue.empty():
            time, oscset = self.rescind_queue.peek()
            if time > t:
                return
            self.rescind_queue.get()   # i.e., pop the item we peeked.
            self.allocated_oscset_queues_by_bank[oscset.bank].remove(oscset)
            self.rescind(oscset)

    def queue_for_return_in_the_future(self, future_time, oscset):
        """Mark that oscset can be returned future_time sec in the future."""
        self.process_rescind_queue()
        rescind_time = now() + future_time
        self.rescind_queue.insert_at_priority(rescind_time, oscset)
        


C0_FREQ = 440.0 / math.pow(2.0, 4 + 9/12)

OSC_SOURCE = OscSource()

class NoteBase:
    oscs_per_note = 0  # How many oscs to request.
    release_time = 0.0  # How long after note_off to hold on to oscs (sec).
    
    # Track all created instances, separate for each derived class.
    # from https://stackoverflow.com/questions/12101958/how-to-keep-track-of-class-instances
    def __new__(cls, midinote, vel):
        instance = super().__new__(cls)
        if "instances" not in cls.__dict__:
            cls.instances = set()
        cls.instances.add(instance)
        return instance

    def __init__(self, midinote, vel):
        self.oscset = OSC_SOURCE.get_oscs(self.oscs_per_note, self.return_oscs)
        self.oscs = self.oscset.oscs
        self.note_on(midinote, vel)
        
    def note_on(self, midinote, vel):
        raise NotImplementedError

    def note_off(self):
        # It's possible the note_off occurs after the note has been
        # rescinded, so watch out.
        if len(self.oscs):
            # Send a note off to the first osc - assumes one has been allocated!
            amy.send(osc=self.oscs[0], vel=0)
            # Mark the oscs as ready for return
            OSC_SOURCE.queue_for_return_in_the_future(self.release_time,
                                                      self.oscset)

    def return_oscs(self):
        """Called when oscs are stolen."""
        self.oscset = None
        self.oscs = []
        # Don't track this object any more.
        self.__class__.instances.remove(self)

    @classmethod
    def broadcast_control_change(cls, control, value):
        try:
            for instance in cls.instances:
                instance.control_change(control, value)
        except:  # instance set not yet created?
            pass


class SimpleNote(NoteBase):
    oscs_per_note = 2
    release_time = 0.250
    
    def note_on(self, midinote, vel):
        osc, modosc = self.oscs
        amy.send(osc=modosc, wave=amy.SINE)
        self.update_lfo()
        amy.send(osc=osc, wave=amy.SAW_DOWN,
                 mod_source=modosc, mod_target=amy.TARGET_FREQ)
        amy.send(osc=self.oscs[0],
                 filter_type=amy.FILTER_LPF,
                 bp0_target=amy.TARGET_AMP,
                 bp1_target=amy.TARGET_FILTER_FREQ)
        self.update_filter()
        self.update_eg0()
        self.update_eg1()
        # Launch the note.
        self.freq = C0_FREQ * math.pow(2, midinote / 12.)
        amy.send(osc=osc, vel=vel, freq=self.freq * current_pitch_bend())

    def update_lfo(self):
        amy.send(osc=self.oscs[1],
                 freq=control_value(LFO_RATE, 0.05, 20),
                 amp=control_value(LFO_AMP, 0.0001, 1.0))

        
    def update_filter(self):
        self.filter_freq = control_value(FILTER_FREQ, 10, 10240)  # 10 octaves
        self.resonance = control_value(FILTER_Q, 0.02, 50)  # Middle value is 1
        amy.send(osc=self.oscs[0],
                 filter_freq=self.filter_freq,
                 resonance=self.resonance)
        
    def update_eg(self, attack_ctl, decay_ctl, sustain_ctl, release_ctl, eg=0):
        attack_ms = int(round(1000. * control_value(attack_ctl, 0.01, 10)))
        decay_ms = int(round(1000. * control_value(decay_ctl, 0.01, 10)))
        sustain_level = "{:.3f}".format(control_value(sustain_ctl, 0., 1., is_log=False))
        release_ms = int(round(1000. * control_value(release_ctl, 0.1, 100)))
        osc = self.oscs[0]
        bp_string = f"0,0,{attack_ms},1.0,{decay_ms},{sustain_level},{release_ms},0"
        if eg == 0:  # EG0 is amplitude.
            amy.send(osc=osc, bp0=bp_string)
        else:  # EG1 is VCF.
            amy.send(osc=osc, bp1=bp_string)

    def update_eg0(self):
        self.update_eg(EG0_ATTACK, EG0_DECAY, EG0_SUSTAIN, EG0_RELEASE, 0)

    def update_eg1(self):
        self.update_eg(EG1_ATTACK, EG1_DECAY, EG1_SUSTAIN, EG1_RELEASE, 1)
                 
    def control_change(self, control, value):
        if control == 0:
            # Pitch bend factor has already been captured, just need to update.
            amy.send(osc=self.oscs[0], freq=self.freq * current_pitch_bend())
        elif control == FILTER_FREQ or control == FILTER_Q:
            # Filter frequency.
            self.update_filter()
        elif (control == EG0_ATTACK or control == EG0_DECAY or
              control == EG0_SUSTAIN or control == EG0_RELEASE):
            self.update_eg0()  # Amplitude EG
        elif (control == EG1_ATTACK or control == EG1_DECAY or
              control == EG1_SUSTAIN or control == EG1_RELEASE):
            self.update_eg1()  # Filter EG
        elif control == LFO_RATE or control == LFO_AMP:
            self.update_lfo()


class FMNote(NoteBase):
    oscs_per_note = 9
    release_time = 0.250  # Depends on patch, this is a guess
    patch = 10  # Default patch is E.PIANO 1.
    
    def note_on(self, midinote, vel):
        osc = self.oscs[0]
        amy.send(osc=osc, wave=amy.ALGO, freq=5, patch=self.patch)
        # Launch the note
        self.freq = C0_FREQ * math.pow(2, midinote / 12.)
        amy.send(osc=osc, vel=vel, freq=self.freq  * current_pitch_bend())

    def control_change(self, control, value):
        if control == 0:
            # Pitch bend factor has already been captured, just need to update.
            amy.send(osc=self.oscs[0], freq=self.freq * current_pitch_bend())
            

PITCH_BEND = 64  # default.

def pitch_bend(bend):
    """Called by midi_event_cb when pitch bend changes."""
    global PITCH_BEND
    PITCH_BEND = bend
    # Function that must be provided to distribute to notes.
    notify_pitch_bend(bend)

def current_pitch_bend():
    """Called by notes to get the current bend factor."""
    # Prevailing pitch bend factor.  +/- 0.5 octave range.
    global PITCH_BEND
    return math.pow(2, (PITCH_BEND - 64) / 128)


NUM_CONTROLS = 128
CONTROL_VALUES = [64] * NUM_CONTROLS

# Oxygen49 slider IDs, starting from left.
SLIDER_IDS = [0x5b, 0x5d, 0x46, 0x47, 0x73, 0x74, 0x75, 0x76, 0x7]

# Oxygen49 knobs, top row then second row.
KNOB_IDS = [0x11, 0x1a, 0x1c, 0x1e, 0x1b, 0x1d, 0xd, 0x4c]

# Oxygen49 buttons.  They toggle between 0 and 0x7f.
BUTTON_IDS = [0x4a, 0x19, 0x77, 0x4f, 0x55, 0x66, 0x6b, 0x70]

# Assignment of Juno-style controls
EG0_ATTACK = SLIDER_IDS[0]
EG0_DECAY = SLIDER_IDS[1]
EG0_SUSTAIN = SLIDER_IDS[2]
EG0_RELEASE = SLIDER_IDS[3]

EG1_ATTACK = SLIDER_IDS[4]
EG1_DECAY = SLIDER_IDS[5]
EG1_SUSTAIN = SLIDER_IDS[6]
EG1_RELEASE = SLIDER_IDS[7]

LFO_RATE = SLIDER_IDS[8]
LFO_AMP = KNOB_IDS[4]

FILTER_FREQ = KNOB_IDS[0]
FILTER_Q = KNOB_IDS[1]


def control_change(control, value):
    global CONTROL_VALUES
    CONTROL_VALUES[control] = value
    notify_control_change(control, value)

def control_value(control, min_val=1, max_val=100, is_log=True):
    """Return a ready-scaled value for a control."""
    if is_log:
        return min_val * math.exp(
            CONTROL_VALUES[control] / 127.0 * math.log(max_val / min_val))
    else:  # Linear.
        return min_val + (max_val - min_val) * (CONTROL_VALUES[control] / 127.0)


NUM_KEYS = 128
KEYNOTES = [None] * NUM_KEYS

def midi_event_cb(x):
  """Callback that takes MIDI note on/off to create Note objects."""
  global KEYNOTES
  m = tulip.midi_in()
  while m is not None:
    #print("midi in: 0x%x 0x%x 0x%x" % (m[0], m[1], m[2]))
    if m[0] == 0x90:  # Note on.
      midinote = m[1]
      midivel = m[2]
      vel = midivel / 127.
      if KEYNOTES[midinote]:
        # Terminate existing instance of this pitch.
        KEYNOTES[midinote].note_off()
      KEYNOTES[midinote] = note_on(midinote, vel)
    elif m[0] == 0x80:  # Note off.
      midinote = m[1]
      if KEYNOTES[midinote]:
        KEYNOTES[midinote].note_off()
        KEYNOTES[midinote] = None
    elif m[0] == 0xc0:  # Program change - choose the DX7 preset
      set_patch(m[1])
    elif m[0] == 0xe0:  # Pitch bend.
      pitch_bend(m[2])
    elif m[0] == 0xb0:  # Other control slider.
      control_change(m[1], m[2])  # e.g.
        
    # Are there more events waiting?
    m = tulip.midi_in()

# Install the callback.
tulip.midi_callback(midi_event_cb)

amy.reset()

###############################################
# Set up methods for voice in use.

def note_on(midinote, velocity):
    return NoteClass(midinote, velocity)

def set_patch(patch):
    NoteClass.patch = patch

def notify_control_change(control, value):
    NoteClass.broadcast_control_change(control, value)

def notify_pitch_bend(bend):
    # Pitch is control 0, value doesn't matter (accessed via current_pitch_bend()).
    NoteClass.broadcast_control_change(0, bend);
    

SYNTH_TYPE = 'dx7'
#SYNTH_TYPE = 'juno'

if SYNTH_TYPE == 'dx7':
    NoteClass = FMNote
elif SYNTH_TYPE == 'juno':
    NoteClass = SimpleNote
else:
    raise ValueError('Unknown SYNTH_TYPE: ' + SYNTH_TYPE)



