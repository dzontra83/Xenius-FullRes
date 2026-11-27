from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
def text_path(txt, cx=12.55, cy=12.45, height=7.0, font=FONT):
    f=TTFont(font); gs=f.getGlyphSet(); cmap=f.getBestCmap()
    capH=getattr(f['OS/2'],'sCapHeight',0) or 1493
    s=height/capH
    adv=sum(gs[cmap[ord(c)]].width for c in txt)
    x0=cx-adv*s/2; y0=cy+height/2
    pen=SVGPathPen(gs, ntos=lambda v: ('%.2f'%v).rstrip('0').rstrip('.'))
    x=0
    for c in txt:
        g=cmap[ord(c)]
        tp=TransformPen(pen,(s,0,0,-s,x0+x*s,y0)); gs[g].draw(tp); x+=gs[g].width
    return pen.getCommands()
if __name__=='__main__':
    import sys
    for t in ('XR','ER','SR'): print(t, len(text_path(t)))
