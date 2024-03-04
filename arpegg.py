"""Arpeggiator for midi input."""

import time
import random

class ArpeggiatorSynth:
  """Create arpeggios."""
  note_on_fn = None
  current_active_notes = None
  arpeggiate_base_notes = None
  octaves = 2
  direction = "up"
  current_note = None
  current_step = -1
  velocity = 1.0
  period_ms = 125
  synth = None
  active = False
  hold = False
  split_note = 60 # 128  # Split is off the end of the keyboard, i.e., inactive.
  
  def __init__(self, synth):
    self.synth = synth
    self.arpeggiate_base_notes = set()
    self.current_active_notes = set()

  def note_on(self, note, vel):
    if not self.active or note >= self.split_note:
      return self.synth.note_on(note, vel)
    if self.hold and not self.current_active_notes:
      # First note after all keys off resets hold set.
      self.arpeggiate_base_notes = set()
    # Adding keys to some already down.
    self.current_active_notes.add(note)
    # Because it's a set, can't get more than one instance of a base note.
    self.arpeggiate_base_notes.add(note)

  def note_off(self, note):
    if not self.active or note >= self.split_note:
      return self.synth.note_off(note)
    #print(self.current_active_notes, self.arpeggiate_base_notes)
    # Update our internal record of keys currently held down.
    self.current_active_notes.remove(note)
    if not self.hold:
      # If not hold, remove notes from active set when released.
      self.arpeggiate_base_notes.remove(note)
      
    
  def full_sequence(self):
    """The full note loop given base_notes, octaves, and direction."""
    # Basic notes, ascending.
    basic_notes = sorted(self.arpeggiate_base_notes)
    # Apply octaves
    notes = []
    for o in range(self.octaves):
      notes = notes + [n + 12 * o for n in basic_notes]
    # Apply direction
    if self.direction == "down":
      notes = notes[::-1]
    elif self.direction == "updown":
      notes = notes + notes[-2:0:-1]
    return notes

  def next_note(self):
    if self.current_note:
      self.synth.note_off(self.current_note)
    sequence = self.full_sequence()
    if sequence:
      if self.direction == "rand":
        self.current_step = random.randint(0, len(sequence) - 1)
      else:
        self.current_step = (self.current_step + 1) % len(sequence)
      self.current_note = sequence[self.current_step]
      self.synth.note_on(self.current_note, self.velocity)

  def run(self):
    while True:
      self.next_note()
      time.sleep_ms(self.period_ms)

  def control_change(self, control, value):
    #if not self.active:
    #  return self.synth.control_change(control, value)
    if control == self.rate_control_num:
      self.period_ms = 25 + 5 * value  #  25 to 665 ms
    elif control == self.octaves_control_num:
      self.cycle_octaves()
    elif control == self.direction_control_num:
      self.cycle_direction()
    else:
      self.control_change_fwd_fn(control, value)

  def cycle_octaves(self):
    self.octaves = 1 + (self.octaves % 3)

  def cycle_direction(self):
    if self.direction == 'up':
      self.direction = 'down'
    elif self.direction == 'down':
      self.direction = 'updown'
    elif self.direction == 'updown':
      self.direction = 'rand'
    else:
      self.direction = 'up'

  def set(self, arg, val=None):
    """Callback for external control."""
    #print("arp set", arg, val)
    #if self.active:
    #  return self.synth.set(arg, val)
    if arg == 'on':
      self.active = val
    elif arg == 'hold':
      self.hold = val
      # Copy across the current_active_notes.
      self.arpeggiate_base_notes = set(self.current_active_notes)
    elif arg == 'arp_rate':
      self.period_ms = int(1000 / (2.0 ** (5 * val)))  # 1 Hz to 32 Hz
    elif arg == 'octaves':
      self.octaves = val
    else:
      self.direction = arg

  def get_new_voices(self, num_voices):
    return self.synth.get_new_voices(num_voices)


# # Plumb into juno.
# execfile('juno_ui.py')
    

# juno_synth = polyvoice.SYNTH
# juno_control_change = polyvoice.control_change_fn

# arp = ArpeggiatorSynth(juno_synth)
# arp.control_change_fwd_fn = juno_control_change
# arp.rate_control_num = KNOB_IDS[7]
# arp.octaves_control_num = BUTTON_IDS[0]
# arp.direction_control_num = BUTTON_IDS[1]


