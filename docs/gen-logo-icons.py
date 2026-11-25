import os, subprocess
OUT = '/tmp/claude-0/-home/42cb8108-c8dc-4be3-a667-6e8a875f868a/scratchpad/logo/out'
ICONS = '/home/vnojsite/site/resources/icons'

PATHS = {
 'C': 'M 757 225 H 495 C 430 225 376 270 376 340 V 410 C 376 465 420 500 470 500 H 757 V 421 H 503 C 487 421 478 410 478 395 V 338 C 478 322 490 311 508 311 H 757 Z',
 'B': 'M 779 225 H 1072 C 1122 225 1153 255 1153 300 C 1153 328 1138 350 1113 361 C 1148 368 1162 395 1162 424 C 1162 470 1130 500 1078 500 H 779 Z M 873 299 H 1037 Q 1051 299 1051 313 Q 1051 331 1033 331 H 873 Z M 873 398 H 1037 Q 1053 398 1053 414 Q 1053 430 1035 430 H 873 Z',
 'N': 'M 376 516 H 484 L 653 653 V 516 H 757 V 795 H 651 L 480 653 V 795 H 376 Z',
 'P': 'M 779 795 V 600 Q 779 516 865 516 H 1043 V 636 Q 1043 686 990 686 H 885 V 795 Z',
 'D': 'M 1066 516 H 1160 V 610 H 1066 Z',
 'J': 'M 1066 633 H 1160 V 675 Q 1160 795 1030 795 H 908 V 709 H 1003 Q 1066 709 1066 645 Z',
}
GRADS = '''<defs>
<linearGradient id="gC" gradientUnits="userSpaceOnUse" x1="376" y1="225" x2="757" y2="500"><stop offset="0" stop-color="#00006e"/><stop offset="0.55" stop-color="#0000b4"/><stop offset="1" stop-color="#0000f0"/></linearGradient>
<linearGradient id="gB" gradientUnits="userSpaceOnUse" x1="800" y1="225" x2="1162" y2="500"><stop offset="0" stop-color="#0030ff"/><stop offset="0.55" stop-color="#0000ff"/><stop offset="1" stop-color="#00008c"/></linearGradient>
<linearGradient id="gN" gradientUnits="userSpaceOnUse" x1="376" y1="795" x2="757" y2="516"><stop offset="0" stop-color="#0028ff"/><stop offset="0.5" stop-color="#0000c8"/><stop offset="1" stop-color="#00007c"/></linearGradient>
<linearGradient id="gJ" gradientUnits="userSpaceOnUse" x1="779" y1="516" x2="1160" y2="795"><stop offset="0" stop-color="#00007a"/><stop offset="0.55" stop-color="#0000b0"/><stop offset="1" stop-color="#0000f2"/></linearGradient>
</defs>'''
FILL = {'C': 'url(#gC)', 'B': 'url(#gB)', 'N': 'url(#gN)', 'P': 'url(#gJ)', 'D': 'url(#gJ)', 'J': 'url(#gJ)'}

def mark(kind):
    out = []
    for k, d in PATHS.items():
        fill = FILL[k] if kind == 'color' else ('#ffffff' if kind == 'white' else '#000000')
        rule = ' fill-rule="evenodd"' if k == 'B' else ''
        out.append('<path fill="%s"%s d="%s"/>' % (fill, rule, d))
    return ''.join(out)

def svg(viewbox, body, w=None, h=None, extra=''):
    wh = (' width="%s" height="%s"' % (w, h)) if w else ''
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s"%s%s>%s</svg>\n' % (viewbox, wh, extra, body)

def write(path, s):
    open(path, 'w').write(s)

TIGHT = '376 225 786 570'
# --- logo files (tight) ---
write(OUT + '/logo-color.svg', svg(TIGHT, GRADS + mark('color'), 262, 190))
write(OUT + '/logo-white.svg', svg(TIGHT, mark('white'), 262, 190))
write(OUT + '/logo.svg', svg(TIGHT, mark('white'), 262, 190))     # navbar fallback: dark bar -> white
# safari pinned tab: monochrome, square view box
write(OUT + '/safari-pinned-tab.svg', svg('376 117 786 786', mark('mono')))

def icon_svg(size, rounded, scale_w):
    rx = round(size * 112 / 512) if rounded else 0
    s = scale_w / 786.0
    mw, mh = scale_w, 570 * s
    tx, ty = (size - mw) / 2.0, (size - mh) / 2.0
    bg = ('<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a0a9c"/>'
          '<stop offset="0.55" stop-color="#0000e6"/><stop offset="1" stop-color="#0036ff"/></linearGradient></defs>')
    body = bg + '<rect width="%d" height="%d" rx="%d" fill="url(#bg)"/>' % (size, size, rx)
    body += '<g transform="translate(%.2f %.2f) scale(%.5f) translate(-376 -225)">%s</g>' % (tx, ty, s, mark('white'))
    return svg('0 0 %d %d' % (size, size), body, size, size)

write(OUT + '/icon.svg', icon_svg(512, True, 400))
# source SVGs for raster
write(OUT + '/_icon_round.svg', icon_svg(512, True, 400))
write(OUT + '/_icon_square.svg', icon_svg(512, False, 400))
write(OUT + '/_logo_color_pad.svg', svg('326 175 886 670', GRADS + mark('color')))
# og image: white bg, color logo
og = ('<rect width="1200" height="630" fill="#ffffff"/>'
      '<g transform="translate(%.2f %.2f) scale(%.5f) translate(-376 -225)">%s%s</g>') % (
      (1200 - 680) / 2.0, (630 - 570 * 680 / 786.0) / 2.0, 680 / 786.0, GRADS, mark('color'))
write(OUT + '/_og.svg', svg('0 0 1200 630', og, 1200, 630))

def png(src, dst, w, h=None):
    h = h or w
    subprocess.check_call(['rsvg-convert', '-w', str(w), '-h', str(h), OUT + '/' + src, '-o', OUT + '/' + dst])

for n in (16, 32, 96):
    png('_icon_round.svg', 'favicon-%dx%d.png' % (n, n), n)
for n in (36, 48, 72, 96, 144, 192, 256, 384, 512):
    png('_icon_round.svg', 'android-chrome-%dx%d.png' % (n, n), n)
for n in (57, 60, 72, 76, 114, 120, 144, 152, 180):
    png('_icon_square.svg', 'apple-touch-icon-%dx%d.png' % (n, n), n)
png('_icon_square.svg', 'apple-touch-icon.png', 180)
png('_icon_square.svg', 'apple-touch-icon-precomposed.png', 180)
for n in (70, 144, 150, 310):
    png('_icon_square.svg', 'mstile-%dx%d.png' % (n, n), n)
png('_og.svg', 'og_logo.png', 1200, 630)
png('_logo_color_pad.svg', 'logo.png', 800, 605)


FAV_GRAD = '<defs><linearGradient id="fv" gradientUnits="userSpaceOnUse" x1="376" y1="225" x2="1162" y2="795"><stop offset="0" stop-color="#3d6bff"/><stop offset="1" stop-color="#0a2cff"/></linearGradient></defs>'
fav_body = FAV_GRAD + ''.join('<path fill="url(#fv)"%s d="%s"/>' % (' fill-rule="evenodd"' if k == 'B' else '', d) for k, d in PATHS.items())
write(OUT + '/_favicon.svg', svg('376 150 786 720', fav_body))
for n in (16, 32, 48, 96):
    png('_favicon.svg', '_fav-%d.png' % n, n)
import shutil
for n in (16, 32, 96):
    shutil.copy(OUT + '/_fav-%d.png' % n, OUT + '/favicon-%dx%d.png' % (n, n))

# favicon.ico (16, 32, 48)
from PIL import Image
base = Image.open(OUT + '/_fav-48.png').convert('RGBA')
imgs = [Image.open(OUT + '/_fav-16.png').convert('RGBA'), Image.open(OUT + '/_fav-32.png').convert('RGBA'), base]
imgs[2].save(OUT + '/favicon.ico', format='ICO', sizes=[(16, 16), (32, 32), (48, 48)], append_images=imgs[:2])
print(sorted(os.listdir(OUT)))
