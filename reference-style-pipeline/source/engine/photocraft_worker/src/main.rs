//! HarnessIR adapter extension. No generic command dispatch or ambient input paths.
//! Private job directory. Explicit ICC-bound RGB U16 document channels; no implicit
//! color transform. U16 transport; coverage masks bind to real LayerMask surfaces.
use std::{collections::BTreeMap, fs, io::{Read, Write}};
use photocraft_doc::{Document, Layer, LayerContent, LayerMask, Surface, PixelFormat, ColorMode, SampleType, Size, Adjustment};
use photocraft_doc::adjust::{curve_map, ToneSpace};
use serde::Deserialize;
const COMMIT: &str = "b1794c6e0608ccfc887213dcf58398977c5cb75e";
const PROTOCOL: &str = "harnessir_photocraft_channels_v6";
const P3_PROFILES: [&str; 2] = ["d77bd8c4008f1813dca5e67762872667734f796a188b52123db65fd5fda262a9", "0ff6958f98684c61f6bbdce1368ddeaf3873baf84545baba482e920d92a914c0"];
const SRGB_PROFILE: &str = "6f6fe5cc53cd24ceeb7997fb24ce2889fdfb88d88ce4fdc5f8e25e0481294953";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request { protocol: String, width: u32, height: u32, domain_id: String, working_icc_sha256: String, operations: Vec<Operation> }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Operation { tool: String, mask: bool, values: BTreeMap<String, f32> }
fn samples(path: &str, count: usize) -> Result<Vec<f32>, Box<dyn std::error::Error>> {
    let bytes=fs::read(path)?;
    if bytes.len()!=count*4 { return Err("sample count mismatch".into()); }
    let mut out=Vec::with_capacity(count);
    for b in bytes.chunks_exact(4) {
        let v=f32::from_le_bytes([b[0],b[1],b[2],b[3]]);
        if !v.is_finite() || !(0.0..=1.0).contains(&v) {return Err("nonfinite/out-of-range sample".into());}
        out.push(v);
    }
    Ok(out)
}
fn parameter(v: &BTreeMap<String,f32>, k: &str, lo: f32, hi: f32)->Result<f32,Box<dyn std::error::Error>> {
    let n=*v.get(k).ok_or("missing parameter")?;
    if !n.is_finite() || n<lo || n>hi {return Err("parameter bounds".into());} Ok(n)
}
fn source_u16(path: &str, count: usize) -> Result<Vec<f32>, Box<dyn std::error::Error>> {
    let bytes=fs::read(path)?;
    if bytes.len()!=count*2 { return Err("U16 source sample count mismatch".into()); }
    Ok(bytes.chunks_exact(2).map(|b|u16::from_le_bytes([b[0],b[1]]) as f32/65535.0).collect())
}
fn verified_profile(domain: &str, expected: &str, bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    let allowed: &[(&str, &[u8])] = match domain {
        "display_p3" => &[
            ("d77bd8c4008f1813dca5e67762872667734f796a188b52123db65fd5fda262a9", include_bytes!("../profiles/d77bd8c4008f1813dca5e67762872667734f796a188b52123db65fd5fda262a9.icc")),
            ("0ff6958f98684c61f6bbdce1368ddeaf3873baf84545baba482e920d92a914c0", include_bytes!("../profiles/0ff6958f98684c61f6bbdce1368ddeaf3873baf84545baba482e920d92a914c0.icc")),
        ],
        "srgb" => &[(SRGB_PROFILE, include_bytes!("../profiles/6f6fe5cc53cd24ceeb7997fb24ce2889fdfb88d88ce4fdc5f8e25e0481294953.icc"))],
        _ => return Err("unsupported document domain".into()),
    };
    if !allowed.iter().any(|(hash, profile)| *hash==expected && *profile==bytes) {
        return Err("working ICC hash/bytes/domain mismatch".into());
    }
    Ok(())
}
fn run()->Result<(),Box<dyn std::error::Error>> {
    if std::env::args().nth(1).as_deref()==Some("--capabilities") {
        println!("{}",serde_json::json!({"protocol":PROTOCOL,"adapter_version":"p3-material-controller-v6","balance_parameter_range":[-100,100],"gamma_parameter_range":[0.67,2.0],"brightness_contrast_parameter_range":[-30,30],"commit":COMMIT,"backend":"cpu","document":"RGB_U16_document_channels","input":"RGB_U16_LE_document_channels","output":"RGB_U16_LE_document_channels","supported_domains":{"srgb":[SRGB_PROFILE],"display_p3":P3_PROFILES},"implicit_color_transform":false,"mask":"HarnessIR Surface/LayerMask extension","tools":["exposure","curve","balance","saturation","gamma","brightness_contrast"],"channel_semantics":{"exposure":"gamma2.2 channel transfer, not physical P3 EV","saturation":"upstream .288R+.712G grey, not P3 Y","balance":"upstream preserve_luminosity, not P3 Y"}}));return Ok(());
    }
    let mut text=String::new();fs::File::open("request.json")?.take(65537).read_to_string(&mut text)?;
    if text.len()>65536 {return Err("request size".into());}
    let r:Request=serde_json::from_str(&text)?;
    if r.protocol!=PROTOCOL {return Err("worker protocol mismatch".into());}
    let n=u64::from(r.width)*u64::from(r.height);
    if n==0 || n>50_000_000 || r.operations.len()>6 {return Err("job budget".into());}
    let mut doc=Document::new("HarnessIR",Size::new(r.width,r.height),ColorMode::Rgb,SampleType::U16);
    let profile=fs::read("working.icc")?;
    if profile.len()>4_000_000 {return Err("profile size".into());}
    verified_profile(&r.domain_id, &r.working_icc_sha256, &profile)?;
    doc.icc_profile=Some(std::sync::Arc::new(profile));
    let rgb=source_u16("source.u16",n as usize*3)?;
    let mut rgba=Vec::with_capacity(n as usize*4);
    for p in rgb.chunks_exact(3) {rgba.extend_from_slice(p);rgba.push(1.0);}
    let rect=doc.bounds();let mut source=Surface::new(PixelFormat::RGBA16);
    source.try_write_region(rect,&rgba)?;doc.layers.push(Layer::new("original A",LayerContent::Raster(source)));
    for (i,op) in r.operations.iter().enumerate() {
        let v=&op.values;
        let adj=match op.tool.as_str() {
            "exposure" if v.len()==1=>Adjustment::Exposure { exposure:parameter(v,"ev",-1.,1.)?,offset:0.,gamma:1. },
            "gamma" if v.len()==1=>Adjustment::Exposure { exposure:0.,offset:0.,gamma:parameter(v,"gamma",0.67,2.)? },
            "brightness_contrast" if v.len()==2=>Adjustment::BrightnessContrast { brightness:parameter(v,"brightness",-30.,30.)?,contrast:parameter(v,"contrast",-30.,30.)?,legacy:false },
            "saturation" if v.len()==1=>Adjustment::Vibrance { vibrance:0.,saturation:parameter(v,"amount",-20.,20.)? },
            "balance" if v.len()==2=>Adjustment::ColorBalance { shadows:[0.;3],midtones:[parameter(v,"red",-100.,100.)?,0.,parameter(v,"blue",-100.,100.)?],highlights:[0.;3],preserve_luminosity:true },
            "curve" if v.len()==1=>{
                let mid=parameter(v,"mid",96.,160.)?;
                // Monotone piecewise-linear 0..255 map, explicit domain conversion.
                let map:Vec<f32>=(0..256).map(|k| {let x=k as f32;if x<=128. {x*mid/128./255.} else {(mid+(x-128.)*(255.-mid)/127.)/255.}}).collect();
                Adjustment::Curves { master:curve_map(&map),per_channel:[vec![],vec![],vec![]],space:ToneSpace::Rgb,black:vec![],pencil:true }
            },
            _=>return Err("unknown tool or parameter keys".into()),
        };
        let mut layer=Layer::new(format!("operation {i}"),LayerContent::Adjustment(adj));
        if op.mask {
            let mask=samples(&format!("mask{i}.f32"),n as usize)?;
            let mut surface=Surface::new(PixelFormat::new(ColorMode::Grayscale,SampleType::U16,false));
            surface.try_write_region(rect,&mask)?;
            layer.mask=Some(LayerMask{surface,enabled:true,linked:true,density:1.,feather:0.});
        }
        doc.layers.push(layer);
    }
    // Native CPU float composition, explicitly never automation::files::render_png.
    let image=photocraft_compose::render(&doc,rect);
    let mut output=std::io::BufWriter::new(fs::OpenOptions::new().write(true).create_new(true).open("output.u16")?);
    for p in image.px {
        if p.iter().any(|v| !v.is_finite()) || (p[3]-1.).abs()>1e-6 {return Err("invalid rendered sample/alpha".into());}
        for v in &p[..3] {
            if !(0.0..=1.0).contains(v) {return Err("out-of-SDR rendered channel".into());}
            let q=(v*65535.0).round() as u16;output.write_all(&q.to_le_bytes())?;
        }
    }
    output.flush()?;
    println!("{}",serde_json::json!({"commit":COMMIT,"backend":"cpu","width":r.width,"height":r.height,"warnings":[],"protocol":PROTOCOL,"adapter_version":"p3-material-controller-v6","document":"RGB_U16_document_channels","input":"RGB_U16_LE_document_channels","output":"RGB_U16_LE_document_channels","domain_id":r.domain_id,"working_icc_sha256":r.working_icc_sha256,"implicit_color_transform":false}));
    Ok(())
}
fn main(){if let Err(e)=run(){eprintln!("{e}");std::process::exit(2);}}
