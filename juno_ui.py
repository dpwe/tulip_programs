"""juno_ui: GUI for controlling Juno patches."""
import juno

registered_callbacks = {}

def register_callback(id_, callback):
  global registered_callback
  registered_callbacks[id_] = callback

def ui_callback(x):
  # x is the element ID that was triggered
  global registered_callback
  if x in registered_callbacks:
    registered_callbacks[x](x)
  else:
    print("Unrecognized element:", x)

tulip.ui_callback(ui_callback)


class IdFactory:
  id = 0

  @classmethod
  def next_id(cls):
    id = cls.id
    cls.id += 1
    return id


class UIBase:
  """Base class for UI elements, supports placing before drawing."""
  x = 0
  y = 0
  w = 100
  h = 100
  fg_color = tulip.color(100, 100, 100)
  bg_color = tulip.color(0, 0, 0)
  text_color = tulip.color(255, 255, 255)
  body_font = 8
  text_height = 12
  title_font = 5
  
  def __init__(self, name="<none>"):
    self.name = name
    # Update w, h here or in place()

  def place(self, x, y):
    self.x = x
    self.y = y

  def draw(self):
    """Replace with actual."""
    tulip.bg_rect(self.x, self.y, self.w, self.h, self.fg_color, False)
    tulip.bg_str(self.title, self.x, self.y + self.text_height,
                 self.text_color, self.title_font, 
                 self.w, 2 * self.text_height)


class Slider(UIBase):
  w_sli = 10
  y_sli = 12
  h_sli = 200
  y_txt = 0
  y_val = 235
  val = 0
  padx = 15
  w_leg = 26
  
  def __init__(self, name, callback=None):
    super().__init__(name)
    self.value_callback_fn = callback
    self.id_ = IdFactory.next_id()
    self.w = self.w_sli + 2 * self.padx
    self.h = self.y_val + 2 * self.text_height

  def draw(self):
    tulip.ui_slider(self.id_, self.val,
                    self.x + self.w_leg,
                    self.y + self.y_sli, self.w_sli, self.h_sli,
                    self.fg_color, self.bg_color)
    tulip.ui_active(self.id_, 1)
    register_callback(self.id_, self.callback)
    tulip.bg_str(self.name, self.x + self.w_leg - self.padx,
                 self.y + self.y_txt - self.text_height // 2,
                 self.text_color, self.body_font, 2 * self.padx, self.text_height)
    thumb_height = self.h_sli // 10
    # Slider legend.
    for i in range(11):
      tulip.bg_str(str(10 - i), self.x - self.padx + self.w_leg,
                   self.y + self.y_sli - (self.text_height - thumb_height) // 2 + (i * self.h_sli) // 11,
                   self.text_color, self.body_font, self.padx, self.text_height)
    self.set_val(self.val)
    
  def set_val(self, v):
    self.val = v
    x = self.x + self.w_leg - self.padx
    y = self.y + self.y_val - self.text_height // 2
    w = 2 * self.padx
    h = self.text_height
    tulip.bg_rect(x, y, w, h, self.bg_color, True)
    tulip.bg_str("%.2f" % self.val, x, y, self.text_color, self.body_font, w, h)
    tulip.ui_slider(self.id_, self.val)
    if self.value_callback_fn is not None:
      self.value_callback_fn(self.val)

  def callback(self, id_):
    self.set_val(tulip.ui_slider(id_))


class ControlledLabel(UIBase):
  """A label with some press-to-act buttons (e.g. + and -)."""
  button_size = 16
  button_space = 4
  total_height = 40
  total_width = 200
  
  def __init__(self, name, button_labels, callbacks, text):
    super().__init__(name)
    self.w = self.total_width
    self.h = self.total_height
    self.button_labels = button_labels
    self.callbacks = callbacks
    self.text = text
    
  def draw(self):
    x = self.x
    y = self.y
    w = self.button_size
    h = self.button_size
    dh = self.button_space
    self.ids = []
    for tag in self.button_labels:
      id_ = IdFactory.next_id()
      tulip.ui_button(id_, tag, x, y, w, h, self.bg_color, self.text_color, False, self.body_font) 
      
      tulip.ui_active(id_, 1)
      self.ids.append(id_)
      register_callback(id_, self.callback)
      y = y + h + dh
    self.redraw_text()

  def redraw_text(self):
    # Label box
    y = self.y
    x = self.x + self.button_size + self.button_space
    w = self.w - self.button_size - self.button_space
    h = self.h
    tulip.bg_rect(x, y, w, h, self.bg_color, True)
    tulip.bg_str(self.text, x, y, self.text_color, self.body_font, w, h)
    
  def set_text(self, text):
    self.text = text
    self.redraw_text()

  def callback(self, ui_id):
    # Dispatch to provided per-button callbacks
    for id_, callback in zip(self.ids, self.callbacks):
      if ui_id == id_:
        callback()

  def press(self, button_text):
    """Simulate a button press."""
    for label, callback in zip(self.button_labels, self.callbacks):
      if button_text == label:
        callback()



class ButtonSet(UIBase):
  y_top = 24
  y_txt = 0
  y_spacing = 44
  padx = 10
  button_w = 10
  text_height = 12

  def __init__(self, name, tags, callbacks=None, checkbox_style=0):
    super().__init__(name)
    if callbacks is None:
      callbacks = [None] * len(tags)
    self.value_callback_fns = {tag: callback for tag, callback in zip(tags, callbacks)}
    # Update geometry
    self.w = 2 * self.padx
    self.h = self.y_top + len(tags) * self.y_spacing
    # Set up state
    self.tags = tags
    self.checkbox_style = checkbox_style
    self.ids = []
    self.state = {}
    for tag in self.tags:
      self.state[tag] = False

  def draw(self):
    x = self.x + self.padx
    y = self.y + self.y_txt
    tulip.bg_str(self.name, x - self.padx, y - self.text_height // 2,
                 self.text_color, self.body_font,
                 2 * self.padx, self.text_height)
    y = self.y + self.y_top
    for tag in self.tags:
      tulip.bg_str(tag, x - self.padx, y - self.text_height // 2,
                   self.text_color, self.body_font,
                   2 * self.padx, self.text_height)
      y = y + self.text_height
      id_ = IdFactory.next_id()
      tulip.ui_checkbox(id_, self.state[tag],
                        x - self.button_w // 2, y, self.button_w,
                        self.fg_color, self.bg_color, self.checkbox_style)
      tulip.ui_active(id_, 1)
      self.ids.append(id_)
      register_callback(id_, self.callback)
      y = y + (self.y_spacing - self.text_height)


class RadioButton(ButtonSet):

  def __init__(self, name, tags, callbacks):
    # checkbox_style: 0 is filled box, 1 is X, 2 is filled circle
    super().__init__(name, tags, callbacks, 2)
  
  def set_val(self, tag):
    for id_, button_tag in zip(self.ids, self.tags):
      if button_tag == tag:
        tulip.ui_checkbox(id_, True)
        self.state[button_tag] = True
      else:
        tulip.ui_checkbox(id_, False)
        self.state[button_tag] = False
      if self.value_callback_fns[button_tag] is not None:
        self.value_callback_fns[button_tag](self.state[button_tag])

  def callback(self, ui_id):
    # RadioButton deselects all other buttons.
    for id_, button_tag in zip(self.ids, self.tags):
      if ui_id == id_:
        self.set_val(button_tag)
        

class OptionButtons(ButtonSet):

  def __init__(self, name, tags, callbacks):
    # checkbox_style: 0 is filled box, 1 is X, 2 is filled circle
    super().__init__(name, tags, callbacks, 1)
    self.values = {}
    for id_, tag in zip(self.ids, self.tags):
      self.state[tag] = False
  
  def set_val(self, tag, val):
    for id_, button_tag in zip(self.ids, self.tags):
      if button_tag == tag:
        tulip.ui_checkbox(id_, val)
        self.state[button_tag] = val
      if self.value_callback_fns[button_tag] is not None:
        self.value_callback_fns[button_tag](self.state[button_tag])

  def callback(self, ui_id):
    for id_, button_tag in zip(self.ids, self.tags):
      if ui_id == id_:
        self.set_val(button_tag, tulip.ui_checkbox(id_))


class UIGroup(UIBase):
  inset_x = 5
  inset_y = 5
  top_height = 30
  top_color = tulip.color(255, 0, 0)
  
  def __init__(self, name, elements):
    super().__init__(name)
    self.elements = elements
    
  def place(self, x, y):
    self.x = x
    self.y = y
    x = self.x + self.inset_x
    y = self.y + self.top_height + 2 * self.inset_y
    h = 0
    for element in self.elements:
      element.place(x, y)
      x += element.w + self.inset_x
      h = element.h if element.h > h else h
    self.w = x - self.x
    self.h = h + self.top_height + 2 * self.inset_y

  def draw(self):
    if self.name:
      # Draw frame.
      tulip.bg_rect(self.x, self.y, self.w, self.h, self.fg_color, False)
      # Draw title.
      tulip.bg_rect(self.x, self.y, self.w, self.top_height, self.top_color, True)
      tulip.bg_str(self.name, self.x, self.y,
                   self.text_color, self.title_font, 
                   self.w, self.top_height)
    # Draw elements.
    for element in self.elements:
      element.draw()


def setup_from_patch(patch_number):
  """Make the UI match the values in a JunoPatch."""
  patch = juno.JunoPatch.from_patch_number(patch_number)
  for el in ['lfo_rate', 'lfo_delay_time',
             'dco_lfo', 'dco_pwm', 'dco_sub', 'dco_noise',
             'vcf_freq', 'vcf_res', 'vcf_env', 'vcf_lfo', 'vcf_kbd',
             'vca_level', 'env_a', 'env_d', 'env_s', 'env_r']:
    # globals()[el] is the (UI) object with that name
    # getattr(patch, el) is that member of the patch object
    globals()[el].set_val(getattr(patch, el))

  dco_range.set_val("4'" if patch.stop_4 else "16'" if patch.stop_16 else "8'")
  dco_pwm_mode.set_val('Man' if patch.pwm_manual else 'LFO')
  dco_wave.set_val('Pulse', patch.pulse)
  dco_wave.set_val('Saw', patch.saw)
  hpf_freq.set_val(str(patch.hpf))
  vcf_pol.set_val('Neg' if patch.vcf_neg else 'Pos')
  vca_mode.set_val('Gate' if patch.vca_gate else 'Env')
  chorus_mode.set_val(['Off', 'I', 'II', 'III'][patch.chorus])

  return patch.name


class PatchHolder:
  patch_num = 0

  def patch_up(self):
    self.patch_num = (self.patch_num + 1) % 128
    self.new_patch()

  def patch_down(self):
    self.patch_num = (self.patch_num + 127) % 128
    self.new_patch()

  def new_patch(self, patch_num=None):
    if patch_num is not None:
      self.patch_num = patch_num
    patch_name = setup_from_patch(self.patch_num)
    patch_selector.set_text(patch_name)


import juno
jp = juno.JunoPatch.from_patch_number(20)
jp.init_AMY()
#alles.send(osc=0, note=60, vel=1)

# Make the callback function.
def jcb(arg):
  callback = lambda x: jp.set_param(arg, x)
  return callback

lfo_rate = Slider('Rate', jcb('lfo_rate'))
lfo_delay_time = Slider('Delay', jcb('lfo_delay_time'))

lfo = UIGroup('LFO', [lfo_rate, lfo_delay_time])

dco_range = RadioButton("Range", ["4'", "8'", "16'"],
                        [jcb('stop_4'), jcb('stop_8'), jcb('stop_16')])
dco_lfo = Slider('LFO', jcb('dco_lfo'))
dco_pwm = Slider('PWM', jcb('dco_pwm'))
dco_pwm_mode = RadioButton('PWM', ['LFO', 'Man'], [None, jcb('pwm_manual')])
dco_wave = OptionButtons('Wave', ['Pulse', 'Saw'], [jcb('pulse'), jcb('saw')])
dco_sub = Slider('Sub', jcb('dco_sub'))
dco_noise = Slider('Noise', jcb('dco_noise'))

dco = UIGroup('DCO', [dco_range, dco_lfo, dco_pwm, dco_pwm_mode, dco_wave, dco_sub, dco_noise])

#hpf_freq = Slider('Freq', jcb('hpf'))
def hpf(n):
  callback = lambda x: jp.set_param('hpf', n) if x else None
  return callback
  
hpf_freq = RadioButton('Freq', ['3', '2', '1', '0'],
                       [hpf(3), hpf(2), hpf(1), hpf(0)])
hpf = UIGroup('HPF', [hpf_freq])

vcf_freq = Slider('Freq', jcb('vcf_freq'))
vcf_res = Slider('Res', jcb('vcf_res'))
vcf_pol = RadioButton('Pol', ['Pos', 'Neg'], [None, jcb('vcf_neg')])
vcf_env = Slider('Env', jcb('vcf_env'))
vcf_lfo = Slider('LFO', jcb('vcf_lfo'))
vcf_kbd = Slider('Kybd', jcb('vcf_kbd'))

vcf = UIGroup('VCF', [vcf_freq, vcf_res, vcf_pol, vcf_env, vcf_lfo, vcf_kbd])

vca_mode = RadioButton('Mode', ['Env', 'Gate'], [None, jcb('vca_gate')])
vca_level = Slider('Level', jcb('vca_level'))

vca = UIGroup('VCA', [vca_mode, vca_level])

env_a = Slider('A', jcb('env_a'))
env_d = Slider('D', jcb('env_d'))
env_s = Slider('S', jcb('env_s'))
env_r = Slider('R', jcb('env_r'))

env = UIGroup('ENV', [env_a, env_d, env_s, env_r])

def cho(n):
  callback = lambda x: jp.set_param('chorus', n) if x else None
  return callback

chorus_mode = RadioButton('Mode', ['Off', 'I', 'II', 'III'],
                          [cho(0), cho(1), cho(2), cho(3)])
chorus = UIGroup('CH', [chorus_mode])


juno_ui = UIGroup('', [lfo, dco, hpf, vcf, vca, env, chorus])


patch_holder = PatchHolder()
patch_selector = ControlledLabel("PatchSel", ['+', '-'],
                                 [patch_holder.patch_up, patch_holder.patch_down],
                                 'initial text')
# Juno UI
tulip.bg_clear()

juno_ui.place(10, 30)
juno_ui.draw()

patch_selector.place(800, 20)
patch_selector.draw()
patch_selector.press('+')


# Start the polyvoice
import polyvoice

polyvoice.init(jp, tulip.midi_in)
tulip.midi_callback(polyvoice.midi_event_cb)
