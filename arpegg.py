"""Arpeggiator for midi input."""

import time
import random

class ArpeggiatorSynth:
  """Create arpeggios."""
  note_on_fn = None
  active_notes = None
  octaves = 2
  direction = "up"
  current_note = None
  current_step = -1
  velocity = 1.0
  period_ms = 125
  synth = None
  
  def __init__(self, synth):
    self.synth = synth
    self.active_notes = []

  def note_on(self, note, vel):
    self.active_notes.append(note)
    self.active_notes = sorted(self.active_notes)

  def note_off(self, note):
    note_index = self.active_notes.index(note)
    del self.active_notes[note_index]

  def full_sequence(self):
    """The full note loop given active_notes, octaves, and direction."""
    # Basic notes, ascending.
    basic_notes = sorted(self.active_notes)
    # Apply octaves
    notes = []
    for o in range(self.octaves):
      notes = notes + [n + 12 * o for n in basic_notes]
    # Apply direction
    if self.direction == "down":
      notes = notes[::-1]
    elif self.direction == "updown":
      notes = notes + notes[-2:1:-1]
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
    if control == self.rate_control_num:
      self.period_ms = 25 + 5 * value  # 25 to 665 ms
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


class TestSynth:

  def note_on(self, note, vel):
    print("Note on:", note, vel)

  def note_off(self, note):
    print("Note off:", note)


    
# Plumb into juno.
execfile('juno_ui.py')
    

juno_synth = polyvoice.SYNTH
juno_control_change = polyvoice.control_change_fn

arp = ArpeggiatorSynth(juno_synth)
arp.control_change_fwd_fn = juno_control_change
arp.rate_control_num = KNOB_IDS[7]
arp.octaves_control_num = BUTTON_IDS[0]
arp.direction_control_num = BUTTON_IDS[1]


polyvoice.SYNTH = arp
polyvoice.control_change_fn = arp.control_change

arp.run()
