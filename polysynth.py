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


# Micropython collections.deque does not support remove.
class Queue:
    def __init__(self, maxsize=64):
        self.maxsize = maxsize + 1
        self.queue = [None] * self.maxsize
        self.head = 0
        self.tail = 0

    def next(self, pointer):
        """Incrementing a cicular buffer pointer."""
        return (pointer + 1) % self.maxsize
        
    def prev(self, pointer):
        """Decrementing a cicular buffer pointer."""
        return (pointer + self.maxsize - 1) % self.maxsize
        
    def put(self, item):
        self.queue[self.tail] = item
        self.tail = self.next(self.tail)
        if self.tail == self.head:
            # Wrap around
            self.head = self.next(self.head)
            print("queue: dropped oldest item")

    def _delete_at(self, pointer):
        """Remove the value at queue[pointer], and close up the rest."""
        if self.tail > pointer:
            self.queue[pointer : self.tail - 1] = (
                self.queue[pointer + 1 : self.tail])
            self.tail = self.prev(self.tail)
        elif self.tail < pointer:
            self.queue[pointer : -1] = self.queue[pointer + 1:]
            self.queue[-1] = self.queue[0]
            self.tail = self.prev(self.tail)
        else:
            raise ValueError('pointer at tail???')

    def remove(self, value):
        """Remove first occurrence of value from queue."""
        pointer = self.head
        while pointer != self.tail:
            if self.queue[pointer] == value:
                self._delete_at(pointer)
                return
            pointer = self.next(pointer)
        # Fell through, value wasn't found.
        raise ValueError
            
    def empty(self):
        return self.head == self.tail

    def full(self):
        return self.head == self.next(self.tail)

    def qsize(self):
        return (self.tail - self.head + self.maxsize) % self.maxsize

    def get(self):
        if self.empty():
            # get() on empty queue.
            raise ValueError
        value = self.queue[self.head]
        self.head = self.next(self.head)
        return value

    def __repr__(self):
        result = []
        p = self.head
        while p != self.tail:
            result.append(self.queue[p])
            p = self.next(p)
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

class SimpleNote(NoteBase):
    oscs_per_note = 2
    release_time = 0.250
    
    def note_on(self, midinote, vel):
        osc, modosc = self.oscs
        amy.send(osc=modosc, wave=amy.SINE, freq=5, amp=0.005)
        amy.send(osc=osc, wave=amy.SAW_DOWN, freq=440,
                 mod_source=modosc, mod_target=amy.TARGET_FREQ,
                 filter_freq=500, filter_type=amy.FILTER_LPF)
        amy.send(osc=osc, bp0="5000,0.1,250,0",
                 bp0_target=amy.TARGET_FILTER_FREQ, resonance=0.8)
        amy.send(osc=osc, bp1="100,1.0,8000,0.5,250,0",
                 bp1_target=amy.TARGET_AMP)
        # Launch the note
        amy.send(osc=osc, vel=vel, freq=C0_FREQ * math.pow(2, midinote / 12.))


class FMNote(NoteBase):
    oscs_per_note = 9
    release_time = 0.250  # Depends on patch, this is a guess
    patch = 10  # Default patch is E.PIANO 1.
    
    def note_on(self, midinote, vel):
        osc = self.oscs[0]
        amy.send(osc=osc, wave=amy.ALGO, freq=5, patch=self.patch)
        # Launch the note
        amy.send(osc=osc, vel=vel, freq=C0_FREQ * math.pow(2, midinote / 12.))


# Call this to change the patch being used
def set_patch(patch):
    FMNote.patch = patch


amy.reset()

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
      #KEYNOTES[midinote] = SimpleNote(midinote, vel)
      KEYNOTES[midinote] = FMNote(midinote, vel)
      #print(pitch, vel)
    elif m[0] == 0x80:  # Note off.
      midinote = m[1]
      if KEYNOTES[midinote]:
        KEYNOTES[midinote].note_off()
        KEYNOTES[midinote] = None
    elif m[0] == 0xc0:  # Program change - choose the DX7 preset
      set_patch(m[1])
        
    # Are there more events waiting?
    m = tulip.midi_in()

# Install the callback.
tulip.midi_callback(midi_event_cb)

