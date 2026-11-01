"""Explicit SDR sRGB working domain; high precision PNG avoids Pillow RGB16 truncation.

ICC transforms through Pillow/LittleCMS are restricted to 8-bit input. RGB16 input
must already carry an sRGB profile (or an explicit sRGB assumption). Unknown high
precision profiles fail closed rather than being assigned a new interpretation.
"""
from dataclasses import dataclass,asdict,fields
from pathlib import Path
import hashlib
import io
import struct
import zlib
import warnings
import numpy as np
from PIL import Image, ImageCms, ImageOps

MAX_PIXELS = 50_000_000

def require(ok, message):
    if not ok: raise ValueError(message)

def digest_bytes(x): return hashlib.sha256(x).hexdigest()

def srgb_profile():
    data=bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    data[24:36]=struct.pack('>6H',2000,1,1,0,0,0);data[84:100]=bytes(16)
    return bytes(data)

def linearize(x):
    x=np.asarray(x,dtype=np.float64)
    return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)

def encode_srgb(x):
    x=np.asarray(x,dtype=np.float64)
    return np.where(x<=.0031308,12.92*x,1.055*np.maximum(x,0)**(1/2.4)-.055)

def xyz(rgb,domain=None):return resolve_domain(domain).xyz(rgb)

def luminance(rgb,domain=None):return resolve_domain(domain).luminance(rgb)

def lab(rgb,domain=None):return resolve_domain(domain).lab(rgb)

def image_valid(x):
    require(isinstance(x,np.ndarray) and x.ndim==3 and x.shape[2]==3 and 0<x.shape[0]*x.shape[1]<=MAX_PIXELS,'invalid RGB dimensions')
    require(np.isfinite(x).all() and x.min()>=0 and x.max()<=1,'nonfinite or out-of-SDR pixels')

def _chunks(data):
    require(data[:8]==b'\x89PNG\r\n\x1a\n','not PNG')
    pos=8
    while pos<len(data):
        require(pos+12<=len(data),'truncated PNG')
        n=struct.unpack('>I',data[pos:pos+4])[0];tag=data[pos+4:pos+8];body=data[pos+8:pos+8+n]
        require(pos+12+n<=len(data) and zlib.crc32(tag+body)&0xffffffff==struct.unpack('>I',data[pos+8+n:pos+12+n])[0],'PNG CRC/truncation')
        yield tag,body;pos+=12+n
        if tag==b'IEND': break

def read_png16(path):
    chunks=list(_chunks(Path(path).read_bytes()));header=dict(chunks)[b'IHDR']
    w,h,depth,mode,compression,filtering,interlace=struct.unpack('>IIBBBBB',header)
    require(depth==16 and mode==2 and compression==filtering==interlace==0,'only noninterlaced RGB16 PNG supported')
    require(0<w*h<=MAX_PIXELS,'pixel limit')
    stride=w*6;limit=h*(stride+1);dec=zlib.decompressobj()
    raw=dec.decompress(b''.join(v for k,v in chunks if k==b'IDAT'),limit+1)
    require(len(raw)==limit and dec.eof,'PNG decoded length')
    rows=np.empty((h,stride),dtype=np.uint8);prior=np.zeros(stride,dtype=np.uint8)
    # Bytewise PNG predictors; exact for arbitrary valid filters, no 8-bit RGB conversion.
    for y in range(h):
        kind=raw[y*(stride+1)];row=np.frombuffer(raw[y*(stride+1)+1:(y+1)*(stride+1)],np.uint8).copy()
        require(kind in range(5),'invalid PNG filter')
        if kind==2: row=(row.astype(np.uint16)+prior).astype(np.uint8)
        elif kind:
            for j in range(stride):
                a=int(row[j-6]) if j>=6 else 0;b=int(prior[j]);c=int(prior[j-6]) if j>=6 else 0
                if kind==1:p=a
                elif kind==3:p=(a+b)//2
                else:
                    t=a+b-c; ds=(abs(t-a),abs(t-b),abs(t-c));p=(a,b,c)[ds.index(min(ds))]
                row[j]=(int(row[j])+p)&255
        rows[y]=row;prior=row
    profile=None
    for k,v in chunks:
        if k==b'iCCP':
            name,compressed=v.split(b'\0',1);require(compressed[:1]==b'\0','ICC compression')
            dec=zlib.decompressobj();profile=dec.decompress(compressed[1:],4_000_001)
            require(len(profile)<=4_000_000 and dec.eof,'ICC size')
    return np.frombuffer(rows.tobytes(),'>u2').reshape(h,w,3).astype(np.float64)/65535,dict(bit_depth=16,icc_sha256=digest_bytes(profile) if profile else None,profile=profile,srgb_chunk=any(k==b'sRGB' for k,v in chunks))

def encode_png16(path, rgb,domain=None):
    domain=resolve_domain(domain)
    image_valid(rgb);path=Path(path);require(not path.exists(),'refuse overwrite')
    h,w=rgb.shape[:2];pixels=np.rint(rgb*65535).astype('>u2').tobytes()
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,16,2,0,0,0))
    data+=chunk(b'iCCP',domain.id.encode('ascii')+b'\0\0'+zlib.compress(domain.profile))
    data+=chunk(b'IDAT',zlib.compress(b''.join(b'\0'+pixels[y*w*6:(y+1)*w*6] for y in range(h))))+chunk(b'IEND',b'')
    with path.open('xb') as f:f.write(data)

def _is_srgb(profile):
    # High precision conversion is not available through Pillow's RGB API.
    # Accept only this adapter's exact colorimetric sRGB tags, ignoring profile metadata.
    def tags(data):
        require(len(data)>=132,'ICC header truncated')
        count=struct.unpack('>I',data[128:132])[0];require(132+12*count<=len(data),'ICC table truncated')
        result={}
        for i in range(count):
            signature,offset,size=struct.unpack('>4sII',data[132+12*i:144+12*i])
            require(offset+size<=len(data),'ICC tag truncated')
            result[signature]=data[offset:offset+size]
        return result
    observed=tags(profile);expected=tags(srgb_profile())
    color_tags={b'rXYZ',b'gXYZ',b'bXYZ',b'wtpt',b'rTRC',b'gTRC',b'bTRC',b'chad'}
    require(all(observed.get(k)==expected.get(k) for k in color_tags),'high precision ICC differs from canonical sRGB; explicit high precision conversion required')
    require(profile[16:20]==b'RGB ' and profile[20:24]==b'XYZ ','unsupported ICC color space')

SRGB_MATRIX=((.4124564,.3575761,.1804375),(.2126729,.7151522,.0721750),(.0193339,.1191920,.9503041))
P3_MATRIX=((.4865709486482162,.26566769316909306,.1982172852343625),(.2289745640697488,.6917385218365064,.079286914093745),(0.,.04511338185890264,1.043944368900976))
SRGB_WHITE=(.95047,1.,1.08883)
P3_WHITE=(.9504559270516717,1.,1.0890577507598784)
P3_ICC_SHA256S=frozenset(('d77bd8c4008f1813dca5e67762872667734f796a188b52123db65fd5fda262a9','0ff6958f98684c61f6bbdce1368ddeaf3873baf84545baba482e920d92a914c0'))

def _is_display_p3(profile):
    require(isinstance(profile,bytes) and digest_bytes(profile) in P3_ICC_SHA256S,'Display P3 ICC is not in audited exact-byte allowlist')
    require(profile[16:20]==b'RGB ' and profile[20:24]==b'XYZ ','unsupported P3 ICC color space')
    count=struct.unpack('>I',profile[128:132])[0];tags={}
    for i in range(count):
        signature,offset,size=struct.unpack('>4sII',profile[132+12*i:144+12*i]);require(offset+size<=len(profile),'ICC tag truncated');tags[signature]=profile[offset:offset+size]
    require({b'rXYZ',b'gXYZ',b'bXYZ',b'wtpt',b'chad',b'rTRC',b'gTRC',b'bTRC'}<=set(tags),'P3 matrix/TRC tags missing')
    require(all(digest_bytes(tags[k])=='e94c46a5f3dd96ca3168af4700d0ccb5784d466528ea30b2ef39316af040f2d6' for k in (b'rTRC',b'gTRC',b'bTRC')),'P3 transfer tags mismatch')

@dataclass(frozen=True)
class ColorDomain:
    """Per-image immutable domain; no ambient mutable working-space selection.

    Nominal Display P3 primaries/D65 and shared sRGB transfer are the uniform
    measurement definition. The exact audited source ICC remains the master tag.
    Legacy sRGB Y weights remain rounded as before for backwards numerical behavior.
    """
    id: str
    rgb_to_xyz: tuple
    white_xyz: tuple
    luminance_weights: tuple
    working_profile_hex: str
    transfer: str='srgb'
    def __post_init__(self):
        require(self.id in ('srgb','display_p3') and self.transfer=='srgb','unknown color domain/transfer')
        try:
            matrix=tuple(tuple(row) for row in self.rgb_to_xyz);white=tuple(self.white_xyz);weights=tuple(self.luminance_weights)
            require(all(type(v) in (int,float) and np.isfinite(v) for row in matrix for v in row) and all(type(v) in (int,float) and np.isfinite(v) for v in white+weights),'nonfinite color domain')
            profile=bytes.fromhex(self.working_profile_hex)
        except (TypeError,ValueError) as e:raise ValueError('invalid color domain fields') from e
        expected_matrix=P3_MATRIX if self.id=='display_p3' else SRGB_MATRIX
        expected_white=P3_WHITE if self.id=='display_p3' else SRGB_WHITE
        expected_weights=P3_MATRIX[1] if self.id=='display_p3' else (.2126,.7152,.0722)
        require(matrix==expected_matrix and white==expected_white and weights==expected_weights,'color domain matrix/white/luminance mismatch')
        if self.id=='display_p3':_is_display_p3(profile)
        else:require(profile==srgb_profile(),'sRGB working profile must be exact canonical bytes')
        object.__setattr__(self,'rgb_to_xyz',matrix);object.__setattr__(self,'white_xyz',white);object.__setattr__(self,'luminance_weights',weights)
    @property
    def profile(self):return bytes.fromhex(self.working_profile_hex)
    @property
    def as_dict(self):return asdict(self)
    @property
    def identity(self):
        d=asdict(self);d.pop('working_profile_hex');d['icc_sha256']=digest_bytes(self.profile);return d
    def xyz(self,rgb):return linearize(rgb)@np.asarray(self.rgb_to_xyz).T
    def luminance(self,rgb):return linearize(rgb)@np.asarray(self.luminance_weights)
    def lab(self,rgb):
        t=self.xyz(rgb)/np.asarray(self.white_xyz);d=6/29
        f=np.where(t>d**3,np.cbrt(t),t/(3*d*d)+4/29)
        return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)
    @classmethod
    def from_dict(cls,value):
        require(isinstance(value,dict) and set(value)=={f.name for f in fields(cls)},'unknown or missing ColorDomain fields')
        return cls(**value)

SRGB_DOMAIN=ColorDomain('srgb',SRGB_MATRIX,SRGB_WHITE,(.2126,.7152,.0722),srgb_profile().hex())

def display_p3_domain(profile):return ColorDomain('display_p3',P3_MATRIX,P3_WHITE,P3_MATRIX[1],profile.hex())

def resolve_domain(value=None):
    if value is None:return SRGB_DOMAIN
    if isinstance(value,ColorDomain):return ColorDomain.from_dict(value.as_dict)
    return ColorDomain.from_dict(value)

@dataclass(frozen=True)
class ColorContext:
    source_hash: str
    native_size: tuple
    source_bit_depth: int
    source_icc_sha256: str|None
    assumption: str|None
    orientation: int
    working_domain: str='sRGB IEC61966-2-1 SDR; Y linear; Lab D65'
    operator_domain: str='PhotoCraft RGB U16 display; exposure gamma2.2; curves display 0..255'
    source_format: str|None=None
    frame_count: int=1
    frame_index: int=0
    frame_policy: str='primary_frame_0_SDR_no_HDR_composition'
    domain: ColorDomain=SRGB_DOMAIN

    def __post_init__(self):
        domain=resolve_domain(self.domain);object.__setattr__(self,'domain',domain)
        if domain.id=='display_p3':object.__setattr__(self,'working_domain','Display P3 nominal D65 SDR; shared sRGB transfer; linear Y; Lab D65; original ICC retained')

    @classmethod
    def load(cls,path,assume_srgb=False,working_space='srgb'):
        require(working_space in ('srgb','display_p3'),'unknown working space')
        path=Path(path);raw=path.read_bytes();domain=SRGB_DOMAIN
        with warnings.catch_warnings(record=True) as decode_warnings:
            warnings.simplefilter('always')
            opened=Image.open(path)
        if any('malformed MPO' in str(w.message) for w in decode_warnings):
            opened.close()
            raise ValueError('malformed MPO primary directory unsupported; no silent JPEG fallback')
        with opened as im:
            source_format=im.format;frame_count=getattr(im,'n_frames',1)
            if source_format=='MPO':
                require(type(frame_count) is int and 1<=frame_count<=64,'MPO frame count outside supported 1..64 range')
                im.seek(0)  # Primary SDR JPEG only; never composite gain maps or stereo frames.
            require(im.tell()==0,'input must select primary frame 0')
            require(im.width*im.height<=MAX_PIXELS,'pixel limit')
            orientation=im.getexif().get(274,1);profile=im.info.get('icc_profile')
            high=raw[:8]==b'\x89PNG\r\n\x1a\n' and raw[24]==16
            if high:
                require(orientation==1,'RGB16 orientation must be canonicalized explicitly')
                rgb,meta=read_png16(path);profile=meta['profile']
                if working_space=='display_p3':
                    require(profile is not None,'Display P3 requires an audited ICC, never an assumption')
                    require(not meta['srgb_chunk'],'conflicting sRGB chunk in Display P3 master')
                    domain=display_p3_domain(profile)
                elif profile:_is_srgb(profile)
                else:require(assume_srgb or meta['srgb_chunk'],'missing ICC: explicit sRGB assumption required')
                bits=16
            else:
                require(im.mode=='RGB','only opaque RGB SDR inputs supported; no implicit alpha/RAW/16-bit TIFF conversion')
                require(im.format in ('JPEG','MPO','PNG','WEBP','BMP'),'unsupported source format')
                canonical=ImageOps.exif_transpose(im)
                if working_space=='display_p3':
                    require(profile is not None,'Display P3 requires an audited ICC, never an assumption')
                    require('srgb' not in im.info,'conflicting sRGB chunk in Display P3 input')
                    domain=display_p3_domain(profile)
                elif profile:
                    canonical=ImageCms.profileToProfile(canonical,ImageCms.ImageCmsProfile(io.BytesIO(profile)),ImageCms.createProfile('sRGB'),outputMode='RGB')
                else:require(assume_srgb,'missing ICC: explicit sRGB assumption required')
                rgb=np.asarray(canonical,dtype=np.float64)/255;bits=8
        image_valid(rgb)
        return rgb,cls(digest_bytes(raw),(rgb.shape[1],rgb.shape[0]),bits,digest_bytes(profile) if profile else None,None if profile else 'explicit sRGB',orientation,source_format=source_format,frame_count=frame_count,frame_index=0,domain=domain)

def resize_float(a,size,mask=False):
    w,h=size
    require(w>0 and h>0,'invalid resize')
    if a.shape[:2]==(h,w):return a.copy()
    filt=Image.Resampling.BILINEAR if mask else Image.Resampling.BOX
    if a.ndim==2:return np.asarray(Image.fromarray(a.astype(np.float32)).resize((w,h),filt),dtype=np.float64)
    return np.stack([resize_float(a[...,i],size,mask) for i in range(a.shape[2])],-1)

def preview_size(a,max_side):
    h,w=a.shape[:2];scale=min(1,max_side/max(h,w))
    return max(1,round(w*scale)),max(1,round(h*scale))
