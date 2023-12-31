
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
  w_leg = 30
  
  def __init__(self, name):
    super().__init__(name)
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

  def callback(self, id_):
    self.set_val(tulip.ui_slider(id_))


class ButtonSet(UIBase):
  y_top = 24
  y_txt = 0
  y_spacing = 44
  padx = 10
  button_w = 10
  text_height = 12
  checkbox_style = 0

  def __init__(self, name, tags, checkbox_style):
    super().__init__(name)
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

  def place(self, x, y):
    self.x = x
    self.y = y
      
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

  def __init__(self, name, tags):
    # checkbox_style: 0 is filled box, 1 is X, 2 is filled circle
    super().__init__(name, tags, 2)
  
  def callback(self, ui_id):
    # RadioButton deselects all other buttons.
    for id_, button_tag in zip(self.ids, self.tags):
      if ui_id == id_:
        tulip.ui_checkbox(id_, True)
        self.state[button_tag] = True
      else:
        tulip.ui_checkbox(id_, False)
        self.state[button_tag] = False


class OptionButtons(ButtonSet):

  def __init__(self, name, tags):
    # checkbox_style: 0 is filled box, 1 is X, 2 is filled circle
    super().__init__(name, tags, 1)
    self.values = {}
    for id_, tag in zip(self.ids, self.tags):
      self.state[tag] = False
  
  def callback(self, ui_id):
    # RadioButton deselects all other buttons.
    for id_, tag in zip(self.ids, self.tags):
      if ui_id == id_:
        self.state[tag] = tulip.ui_checkbox(id_)


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

    
# Juno UI
tulip.bg_clear()


lfo_rate = Slider('LFO rate')
lfo_delay = Slider('LFO delay')

lfo = UIGroup('LFO', [lfo_rate, lfo_delay])

dco_range = RadioButton("Range", ["4'", "8'", "16'"])
dco_lfo = Slider('LFO')
dco_pwm = Slider('PWM')
dco_pwm_mode = RadioButton('PWM', ['LFO', 'Manual'])
dco_wave = OptionButtons('Wave', ['Pulse', 'Saw'])
dco_sub = Slider('Sub')
dco_noise = Slider('Noise')

dco = UIGroup('DCO', [dco_range, dco_lfo, dco_pwm, dco_pwm_mode, dco_wave, dco_sub, dco_noise])

hpf_freq = Slider('Freq')
hpf = UIGroup('HPF', [hpf_freq])

vcf_freq = Slider('Freq')
vcf_res = Slider('Res')
vcf_pol = RadioButton('Pol', ['Pos', 'Neg'])
vcf_env = Slider('Env')
vcf_lfo = Slider('LFO')
vcf_kybd = Slider('Kybd')

vcf = UIGroup('VCF', [vcf_freq, vcf_res, vcf_pol, vcf_env, vcf_lfo, vcf_kybd])

vca_mode = RadioButton('Mode', ['Env', 'Gate'])
vca_level = Slider('Level')

vca = UIGroup('VCA', [vca_mode, vca_level])

env_a = Slider('A')
env_d = Slider('D')
env_s = Slider('S')
env_r = Slider('R')

env = UIGroup('ENV', [env_a, env_d, env_s, env_r])

chorus_mode = RadioButton('Mode', ['Off', 'I', 'II', 'III'])
chorus = UIGroup('CH', [chorus_mode])


juno_ui = UIGroup('', [lfo, dco, hpf, vcf, vca, env, chorus])

juno_ui.place(10, 30)
juno_ui.draw()

