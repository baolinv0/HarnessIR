"""Actual root Work visual judgments, written only after inspecting all 15 inputs.

Not detector output, not independent desktop dispatch, not a restoration test.
"""
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parent))
from realzoom_flow import ROOT,BATCH,prepare,diagnose
from hir_manual.storage import read_json,write_json,now,sha256_file

# Individually authored observations of the displayed original input crops.
OBS={
'155':('A blue-bordered Chinese safety notice with a folded/cracked white text panel beside a dark green vertical surface.','Small densely spaced Chinese text is substantially unresolved; the large coloured title is more legible.','Tiny paragraph strokes and the creased lower-right paper','Large title and blue surround','Keep the printed line count, glyph positions, title, existing paper folds and damaged corners; do not replace paragraphs with guessed words.',True,False,'blur','moderate'),
'168':('A framed pale cyan/green civic-values poster with rows of coloured Chinese characters.','Many coloured characters have soft edges and low local separation; the surrounding brown frame retains coarser detail.','Central pale character rows','Outer dark frame','Protect the character arrangement, faded colours, mottled poster surface and frame; do not rewrite the poster from a familiar slogan.',True,False,'softness','moderate'),
'170':('A grey flat panel with a green emblem, Roman-letter wordmark, two Chinese text lines and a small vertical latch.','Fine emblem and text boundaries are slightly soft; broad panel surfaces remain smooth.','Small strokes and emblem contours','Plain grey panel','Retain all existing letters, Chinese glyphs, green logo, latch and panel shading; no guessed brand spelling or redraw.',True,False,'softness','mild'),
'171':('A close view of an irregular black-and-white painted mark on a speckled grey surface, crossed by a horizontal pale seam.','Paint edges are somewhat soft, while the substrate contains dense irregular grain that may be real material texture.','Thin paint drips and fine boundary detail','Large black paint shapes','Preserve the ambiguous painted design, drips, seam and real speckling; do not invent a recognizable object or aggressively remove substrate texture.',False,False,'softness','mild'),
'174':('A close crop of a pale rough granular surface with small holes, darker flecks and tiny reflective points.','Individual grains have weak boundaries; there is no reliable visual basis to classify all granular variation as noise.','Finest grain boundaries','Larger pits and dark inclusions','Keep irregular grains, pores and inclusions. Limit treatment to visible softness without manufacturing a sharper aggregate pattern.',False,False,'softness','mild'),
'175':('A blue rectangular Chinese prohibition sign with two round pictograms, two large white text rows and a smaller issuing line.','Large lettering remains mostly readable but edge transitions and the small bottom line are soft.','Small issuing line and pictogram details','Large white character strokes','Protect exact original text strokes, row arrangement, pictograms, white border and blue background; no literal OCR replacement.',True,False,'softness','mild'),
'176':('A close crop of overlapping pale pink/beige woven threads against darker diagonal fabric bands.','Some individual thread intersections merge, but repeating fine pattern belongs to the woven material.','Small strand intersections','Broad dark/light bands','Preserve thread direction, weave spacing, overlaps and colour. Do not smooth away fabric or synthesize a uniform replacement weave.',False,False,'softness','moderate'),
'179':('A cropped building facade with multiple projecting windows, coloured window frames, vertical wall strips and horizontal trim.','Thin frame edges look soft and slightly uneven; wall and glass have mottled texture at the displayed scale.','Narrow frame corners and small railings','Broad wall divisions','Keep exact window count, opening geometry, projecting ledges, trim perspective and original glass colours; do not invent panes or regularize real crooked edges.',False,True,'softness','moderate'),
'183':('A tightly cropped warm-coloured group of rounded cooked-looking pieces with highlights and deep recesses.','Fine grain is visible across smooth shaded areas, and small surface details are soft.','Dark recesses and smooth brown shading','Large lit rounded forms','Keep the original food-like shapes, glossy highlights, holes and warm colour; distinguish actual porous/crisp texture from noise and do not replace it.',False,False,'noise','moderate'),
'184':('A small crop of pale irregular rounded pieces with dark gaps and a blue region at the top.','Fine grain is widespread and small surface boundaries are soft; exact material is uncertain.','Shaded beige areas and small creases','Coarse object boundaries','Preserve ambiguous material, irregular contours, gaps and the blue background. Do not turn the pieces into a guessed object class.',False,False,'noise','moderate'),
'186':('Two pale vertical door/panel surfaces meet at a centre seam, each with a long rounded brown handle.','Fine coloured/luminance grain is visible over smooth pale panels and handle boundaries are soft.','Flat pale panels and handle transitions','Centre vertical seam','Protect the two handle shapes, spacing, centre seam, relief lines and soft lighting; do not square or reconstruct the hardware.',False,True,'noise','moderate'),
'187':('A soft toy with a pale round face, three dark feature marks, a muted green hood/body and small lower limbs.','Granular noise is conspicuous in shaded fabric and the toy contours are soft.','Dark green fabric and lower shadows','Large pale face area','This is a toy design, not a real human face. Preserve the three feature marks, fabric texture, proportions, colours and all limbs; no beautification or invented fur.',False,False,'noise','moderate'),
'188':('A pastel purple/pink jigsaw puzzle depicting a cartoon character, with a dense network of puzzle-piece seams.','Fine grain/mottling and softness affect cartoon outlines and seam intersections.','Pale cartoon regions and narrow puzzle seams','Larger purple/pink colour regions','Keep every puzzle seam, piece shape, cartoon contour and original colour. Do not redraw the character or remove puzzle joints as artifacts.',False,False,'noise','moderate'),
'189':('Red patterned cloth printed with several white cartoon cats and small decorative flowers.','Fine speckle/mottling overlays some smooth printed areas, while narrow printed contours are slightly soft.','White cat interiors and fine floral boundaries','Larger red background areas','Keep cat count, expressions as printed, decorative motifs, print alignment and fabric variation; do not invent fur or replace the printed pattern.',False,False,'noise','mild'),
'190':('A cluttered indoor shelf/desk crop containing stacked translucent drawers, containers, a green-and-white labelled box and a pale foreground divider.','Noise is prominent in grey shadows and small label strokes are poorly resolved.','Drawer recesses, grey shadows and tiny box label','Large foreground panel','Keep shelf geometry, drawer count, overlaps, all containers and the exact visible label strokes; no object removal or guessed label text.',True,True,'noise','moderate'),
}

def main():
    manifest=prepare();reviews=[]
    for row in manifest['images']:
        sid=row['sample_id'];key=sid.rsplit('_',1)[1];content,evidence,worst,mildest,preserve,text,depth,typ,severity=OBS[key]
        c=ROOT/'cases'/row['cases']['harness'];req=read_json(next((c/'tasks').glob('diagnose_*/request.json')))
        assert req['input_sha256']==row['canonical_sha256']
        # Original files were visibly inspected; canonical RGB equivalence is
        # independently checked to bind those observations to allowed assets.
        with Image.open(row['input_path']) as a,Image.open(c/'input/canonical.png') as b:
            assert a.convert('RGB').tobytes()==b.convert('RGB').tobytes()
        plans=[]
        if text:plans.append(dict(tool='T1_OCR',reason='Obtain source-aligned polygons and recognition confidence for protection only; do not substitute guessed OCR strings for visible strokes.'))
        if depth:plans.append(dict(tool='T3_DEPTH',reason='Inspect relative layering of projecting panels/windows/containers; coarse protection only, no geometry reconstruction or metric-depth claims.'))
        # T2 has no visual justification here; cartoon/printed/toy designs are
        # not actual human identities. T4 explicitly excluded for this trial.
        payload=dict(content=content,degradations=[dict(type=typ,severity=severity,spatial='global',location='Displayed original crop',worst_at=worst,mildest_at=mildest,evidence=evidence)],sensitive=dict(has_text=text,has_faces=False,has_layered_depth=depth,has_complex_semantics=True,notes=preserve+' No actual human face is discernible. T4 evidence is excluded by user; model observations are not detector results.'),tool_plan=plans,difficulty_hint='hard' if text or key in ('176','188') else 'medium',difficulty_reason='Small long-focal-length input contains limited recoverable detail; preservation is more important than apparent sharpness. '+preserve)
        target=BATCH/'diagnoses'/f'{sid}.json'
        if target.exists() and read_json(target)!=payload:raise ValueError('Do not overwrite accepted diagnosis')
        write_json(target,payload)
        diagnose(sid,target)
        reviews.append(dict(sample_id=sid,task_id=req['task_id'],case_id=row['cases']['harness'],viewed_file=row['input_path'],viewed_sha256=sha256_file(Path(row['input_path'])),allowed_asset=req['allowed_assets'][0],canonical_decoded_rgb_equivalence=True,viewer='view_image native size',scope='actual current root Work visual judgment, not desktop dispatch',reviewed_at=now()))
        write_json(BATCH/'visual_reviews.json',reviews)
        print(sid+' diagnosis validated',flush=True)

if __name__=='__main__':main()
