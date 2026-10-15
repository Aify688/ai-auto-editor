"""Global styling. One accent, subtle borders, generous spacing, responsive."""
import streamlit as st

CSS = """
<style>
:root{--ave-accent:#5b8cff;--ave-border:rgba(255,255,255,.10);--ave-muted:rgba(255,255,255,.58);--ave-radius:14px;}
#MainMenu, footer, [data-testid="stToolbar"]{visibility:hidden;}
header[data-testid="stHeader"]{background:transparent;}
.block-container{max-width:1280px;padding-top:2.2rem;padding-bottom:4rem;}
h1,h2,h3{letter-spacing:-.02em;font-weight:650;}
h1{font-size:1.75rem !important;margin-bottom:.15rem;}
.ave-sub{color:var(--ave-muted);margin:0 0 1.4rem 0;font-size:.95rem;}
.ave-label{font-size:.72rem;font-weight:650;letter-spacing:.08em;text-transform:uppercase;color:var(--ave-muted);margin:1.1rem 0 .5rem;}

/* sidebar */
section[data-testid="stSidebar"]{background:#12131a;border-right:1px solid var(--ave-border);}
section[data-testid="stSidebar"] .block-container{padding-top:1.4rem;}
.ave-brand{display:flex;gap:.55rem;align-items:center;font-weight:700;font-size:1.05rem;margin:0 0 1.2rem .2rem;}
.ave-brand i{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,#5b8cff,#8a6bff);display:inline-block;}
section[data-testid="stSidebar"] .stButton>button{justify-content:flex-start;border:0;background:transparent;
  box-shadow:none;padding:.55rem .75rem;border-radius:10px;font-weight:550;}
section[data-testid="stSidebar"] .stButton>button:hover{background:rgba(91,140,255,.08);}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{background:rgba(91,140,255,.12);color:var(--ave-accent);}

/* cards */
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:var(--ave-radius);border-color:var(--ave-border);}
[class*="st-key-card_"]{transition:border-color .15s, box-shadow .15s;}
.ave-chip{display:inline-flex;align-items:center;gap:.3rem;padding:.18rem .6rem;border-radius:999px;
  background:rgba(91,140,255,.09);color:var(--ave-accent);font-size:.78rem;font-weight:600;margin:0 .35rem .35rem 0;}
.ave-chip.mute{background:rgba(255,255,255,.07);color:var(--ave-muted);}
.ave-stat{font-size:1.9rem;font-weight:700;letter-spacing:-.03em;line-height:1.1;}
.ave-statl{color:var(--ave-muted);font-size:.82rem;}

/* steps */
.ave-steps{list-style:none;margin:.6rem 0 0;padding:0;}
.ave-steps li{display:flex;align-items:center;gap:.6rem;padding:.38rem 0;color:var(--ave-muted);font-size:.93rem;}
.ave-steps li .dot{width:20px;height:20px;border-radius:50%;border:2px solid var(--ave-border);display:inline-flex;
  align-items:center;justify-content:center;font-size:.7rem;flex:none;}
.ave-steps li.done{color:inherit;} .ave-steps li.done .dot{background:var(--ave-accent);border-color:var(--ave-accent);color:#fff;}
.ave-steps li.active{color:inherit;font-weight:650;} .ave-steps li.active .dot{border-color:var(--ave-accent);
  animation:avepulse 1.1s ease-in-out infinite;}
@keyframes avepulse{50%{box-shadow:0 0 0 5px rgba(91,140,255,.18);}}

/* video + buttons */
div[data-testid="stVideo"] video{border-radius:var(--ave-radius);background:#000;max-height:68vh;}
.stButton>button,.stDownloadButton>button{border-radius:10px;font-weight:600;}
.stButton>button[kind="primary"]{background:var(--ave-accent);border-color:var(--ave-accent);}
[data-testid="stFileUploaderDropzone"]{border-radius:var(--ave-radius);border:1.5px dashed rgba(91,140,255,.45);
  background:rgba(91,140,255,.04);padding:2.2rem 1rem;}

/* responsive */
@media (max-width: 900px){
  .block-container{padding:1.2rem 1rem 3rem;}
  h1{font-size:1.4rem !important;}
  div[data-testid="stHorizontalBlock"]{flex-wrap:wrap;gap:1rem;}
  div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-width:100% !important;}
  .st-key-presetgrid div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-width:calc(50% - .5rem) !important;}
}
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def selected_card_css(keys: list[str]) -> None:
    rules = "".join(f".st-key-card_{k}{{border:1.5px solid var(--ave-accent) !important;"
                    f"box-shadow:0 0 0 3px rgba(91,140,255,.12);}}" for k in keys)
    st.markdown(f"<style>{rules}</style>", unsafe_allow_html=True)


WORKSPACE_CSS = """
<style>
:root{--ave-tl-h:260px;--ws-top:48px;--ws-main:calc(100vh - var(--ws-top) - var(--ave-tl-h));}
/* Streamlit gives keyed containers flex:1 1 0%, which ignores `height`; pin every workspace block. */
.st-key-ws_root,.st-key-ws_top,.st-key-ws_body,.st-key-ws_rail,.st-key-ws_left,.st-key-ws_right,
.st-key-ws_preview,.st-key-ws_timeline{flex:0 0 auto !important;}
/* the workspace owns the viewport: no page scroll, panels scroll internally */
header[data-testid="stHeader"], [data-testid="stToolbar"], footer, section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"]{display:none !important;}
[data-testid="stMain"], [data-testid="stAppViewContainer"]{overflow:hidden !important;}
[data-testid="stMainBlockContainer"], .block-container{padding:0 !important;max-width:100% !important;}
[data-testid="stApp"]{background:#121419;}
/* st.markdown(<style>) wrappers would otherwise add flex gaps above the workspace */
[data-testid="stElementContainer"]:has(style){display:none !important;}
.st-key-ws_root{height:100vh !important;overflow:hidden !important;gap:0 !important;}
.st-key-ws_top{height:var(--ws-top) !important;background:#1d2027;border-bottom:1px solid #383e49;padding:0 12px !important;
  display:flex;align-items:center;overflow:visible !important;}
.st-key-ws_top [data-testid="stHorizontalBlock"]{width:100%;gap:.35rem !important;align-items:center;}
.st-key-ws_body{height:var(--ws-main) !important;min-height:300px;overflow:hidden !important;}
.st-key-ws_body [data-testid="stHorizontalBlock"]{height:100% !important;gap:0 !important;flex-wrap:nowrap !important;
  align-items:stretch !important;}
.st-key-ws_body [data-testid="stColumn"]{height:100% !important;min-width:0 !important;}
.st-key-ws_rail{background:#1d2027;height:var(--ws-main) !important;border-right:1px solid #383e49;padding:8px 2px !important;gap:2px !important;}
.st-key-ws_rail button{flex-direction:column;gap:2px;height:auto;min-height:0;padding:8px 0;border-radius:8px;color:#a3abb9;}
.st-key-ws_rail button p{font-size:9.5px !important;margin:0;line-height:1.1;}
.st-key-ws_rail button[kind="primary"]{background:rgba(80,140,255,.16);color:#7aa8ff;border:0;}
.st-key-ws_rail button[kind="tertiary"]:hover{background:rgba(255,255,255,.06);color:#fff;}
.st-key-ws_left,.st-key-ws_right{height:var(--ws-main) !important;overflow-y:auto !important;background:#1d2027;padding:12px 12px 24px !important;}
.st-key-ws_left{border-right:1px solid #383e49;} .st-key-ws_right{border-left:1px solid #383e49;}
.st-key-ws_preview{height:var(--ws-main) !important;background:#0b0c10;}
.st-key-ws_preview iframe{height:var(--ws-main) !important;}
.st-key-ws_timeline{height:var(--ave-tl-h) !important;overflow:hidden !important;}
.st-key-ws_timeline iframe{height:var(--ave-tl-h) !important;}
.ws-brand{display:flex;gap:.5rem;align-items:center;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.ws-brand i{width:22px;height:22px;border-radius:6px;background:#508cff;display:inline-block}
.ws-status{color:#a3abb9;font-size:.8rem;white-space:nowrap}
.ws-h{font-size:1rem;font-weight:650;margin:0 0 .15rem}
.ws-sub{color:#a3abb9;font-size:.78rem;margin:0 0 .6rem}
.st-key-ws_top input{height:32px;background:transparent;border:1px solid transparent;font-weight:600}
.st-key-ws_top input:hover,.st-key-ws_top input:focus{border-color:#383e49;background:#262a33}
.st-key-ws_top .stButton>button,.st-key-ws_top [data-testid="stPopover"]>div>button{height:32px;min-height:32px;padding:0 .5rem}
.st-key-ws_right [class*="st-key-card_"]{border:1px solid #383e49;border-radius:8px;padding:3px 6px;margin-bottom:5px;background:#262a33}
.st-key-ws_right [class*="st-key-card_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap !important;gap:.4rem !important;}
.st-key-ws_right [class*="st-key-card_"] button{border:0;background:transparent;justify-content:flex-start;padding:2px 4px;white-space:nowrap;}
.st-key-ws_right [class*="st-key-card_"] button[kind="primary"]{background:transparent;color:#7aa8ff;}
.st-key-ws_left [data-testid="stVerticalBlock"],.st-key-ws_right [data-testid="stVerticalBlock"]{gap:.4rem !important;}
.st-key-ws_right [class*="st-key-card_"] [data-testid="stVerticalBlock"]{gap:0 !important;}
.st-key-ws_right .ave-label{margin:.55rem 0 .3rem;}
.st-key-ws_right [class*="st-key-card_"] button{min-height:30px;height:30px;}
.st-key-ws_right [data-testid="stToggle"]{min-height:26px;}
[data-testid="stLayoutWrapper"]:has(> .st-key-gen_bar),[data-testid="stElementContainer"]:has(> .st-key-gen_bar){
  position:sticky;bottom:-24px;z-index:6;background:#1d2027;margin-top:4px;}
.st-key-gen_bar{padding:10px 0 12px;background:#1d2027;}
.st-key-ws_right [class*="st-key-card_"] .ws-sub{font-size:.7rem;line-height:1.15;}
/* horizontal radio rendered as a compact two-tab switch */
[class*="st-key-ai_asp"] [role="radiogroup"]{gap:6px;}
[class*="st-key-ai_asp"] label{background:#262a33;border:1px solid #383e49;border-radius:6px;padding:3px 10px;margin:0 !important;cursor:pointer;}
[class*="st-key-ai_asp"] label > div:first-child{display:none;}
[class*="st-key-ai_asp"] label:has(input:checked){background:rgba(80,140,255,.2);border-color:#508cff;}
[class*="st-key-ai_asp"] label p{font-size:.78rem;}
.st-key-right_tab,.st-key-right_tab > div{width:100% !important;}
.st-key-right_tab label{white-space:nowrap;}
.st-key-right_tab [role="radiogroup"]{gap:0;background:#262a33;border-radius:8px;padding:2px;width:100%;}
.st-key-right_tab label{flex:1;justify-content:center;padding:5px 8px;border-radius:6px;margin:0 !important;cursor:pointer;}
.st-key-right_tab label > div:first-child{display:none;}
.st-key-right_tab label:has(input:checked){background:#508cff;}
.st-key-right_tab label p{font-size:.82rem;font-weight:600;}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:#383e49 !important;}
</style>
"""


def workspace_css() -> None:
    st.markdown(WORKSPACE_CSS, unsafe_allow_html=True)


PAGE_CSS = """
<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], footer, section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"]{display:none !important;}
[data-testid="stElementContainer"]:has(style){display:none !important;}
[data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"]{background:#0B0E15 !important;}
[data-testid="stMainBlockContainer"], .block-container{padding:0 !important;max-width:100% !important;}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]{gap:0 !important;}
:root{--bg:#0B0E15;--nav:#0F131C;--card:#131924;--card2:#1A2230;--input:#171D29;--line:#293344;--blue:#347DFF;
--blue-h:#2468E8;--tx:#F5F7FC;--tx2:#A0ACBF;--tx3:#738096;}
body, [data-testid="stApp"]{font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--tx);}
/* top navigation */
.st-key-pj_nav{background:var(--nav);border-bottom:1px solid var(--line);height:76px;padding:0 48px !important;
  flex:0 0 auto !important;justify-content:center;}
.st-key-pj_nav [data-testid="stHorizontalBlock"]{align-items:center;gap:.9rem !important;}
.pj-brand{display:flex;align-items:center;gap:.7rem;font-weight:700;font-size:1.25rem;white-space:nowrap;}
.st-key-pj_nav .stButton>button{height:44px;border-radius:10px;background:#131924;border:1px solid var(--line);
  color:var(--tx);font-weight:600;font-size:.92rem;transition:background .15s,border-color .15s;}
.st-key-pj_nav .stButton>button:hover{border-color:#3b4a66;background:#182032;}
.st-key-pj_nav .stButton>button[kind="primary"]{background:var(--blue) !important;border-color:var(--blue) !important;}
.st-key-pj_nav .stButton>button[kind="primary"]:hover{background:var(--blue-h) !important;}
/* page body */
.st-key-pj_page{max-width:1400px;margin:0 auto;padding:30px 40px 56px !important;gap:1.1rem !important;}
.pj-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:6px;}
.pj-head h1{font-size:2.75rem !important;font-weight:800;letter-spacing:-.03em;margin:0;line-height:1.1;color:var(--tx);}
.pj-head p{color:var(--tx2);font-size:1.15rem;margin:.35rem 0 0;}
.pj-deco{opacity:.9;margin-top:-18px;}
/* toolbar */
.st-key-pj_toolbar{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px !important;}
.st-key-pj_toolbar [data-testid="stHorizontalBlock"]{gap:.7rem !important;}
.st-key-pj_toolbar input, .st-key-pj_toolbar [data-baseweb="select"] > div{background:var(--input) !important;
  border:1px solid var(--line) !important;border-radius:10px !important;height:44px;color:var(--tx);}
.st-key-pj_q input{padding-left:42px !important;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='%23738096' stroke-width='2' stroke-linecap='round'><circle cx='11' cy='11' r='8'/><path d='m21 21-4.3-4.3'/></svg>") !important;
  background-repeat:no-repeat !important;background-position:14px center !important;}
.st-key-pj_q input:focus{border-color:var(--blue) !important;box-shadow:0 0 0 1px var(--blue) !important;}
.st-key-pj_new button{height:44px;border-radius:10px;font-weight:700;background:var(--blue) !important;border-color:var(--blue) !important;}
.st-key-pj_new button:hover{background:var(--blue-h) !important;border-color:var(--blue-h) !important;}
/* section headers */
.pj-sec{display:flex;align-items:center;gap:.7rem;margin-top:10px;}
.pj-sec .ic{color:var(--blue);display:flex;}
.pj-sec h2{font-size:1.45rem !important;font-weight:700;margin:0;padding:0;color:var(--tx);}
.pj-count{background:var(--card2);border:1px solid var(--line);color:var(--tx2);font-size:.78rem;
  padding:3px 10px;border-radius:8px;}
[class*="st-key-more_"]{display:flex;justify-content:flex-end;}
[class*="st-key-more_"] button{color:var(--blue) !important;font-weight:600;font-size:.9rem;}
.pj-hr{border:0;border-top:1px solid var(--line);margin:22px 0 4px;}
/* cards */
[class*="st-key-pj_card_"], [class*="st-key-pj_vid_"]{position:relative;background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:16px !important;gap:.55rem !important;transition:border-color .18s,box-shadow .18s;}
[class*="st-key-pj_card_"]:hover, [class*="st-key-pj_vid_"]:hover{border-color:#3d4d6b;box-shadow:0 8px 24px rgba(0,0,0,.35);}
.pj-thumb{position:relative;aspect-ratio:16/9;border-radius:10px;overflow:hidden;background:#0d121b;}
.pj-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
.pj-ph{width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#3a4a66;
  background:linear-gradient(135deg,#141b29,#0e131d);}
.pj-badge{position:absolute;top:10px;right:10px;display:flex;align-items:center;gap:6px;font-size:.74rem;font-weight:600;
  padding:4px 10px;border-radius:999px;background:rgba(14,19,29,.82);border:1px solid #31405b;color:var(--tx);
  backdrop-filter:blur(4px);}
.pj-badge i{width:8px;height:8px;border-radius:50%;display:inline-block;}
.pj-badge.prog i{background:var(--blue);} .pj-badge.draft i{background:#8590a3;} .pj-badge.done i{background:#3ecf8e;}
.pj-play{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:54px;height:54px;border-radius:50%;
  background:rgba(20,24,33,.78);display:flex;align-items:center;justify-content:center;color:#fff;
  border:1px solid rgba(255,255,255,.18);}
.pj-dur{position:absolute;right:10px;bottom:10px;background:rgba(12,16,24,.85);padding:2px 8px;border-radius:6px;
  font-size:.78rem;font-weight:600;}
.pj-title{font-size:1.05rem;font-weight:650;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.pj-meta{display:flex;align-items:center;gap:10px;color:var(--tx3);font-size:.84rem;flex-wrap:wrap;margin:2px 0 12px;}
.pj-meta span{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;}
.pj-meta .sep{width:1px;height:14px;background:var(--line);}
[class*="st-key-pj_card_"] .stButton>button, [class*="st-key-pj_vid_"] .stButton>button,
[class*="st-key-pj_vid_"] .stDownloadButton>button, [class*="st-key-pj_card_"] [data-testid="stPopover"] button,
[class*="st-key-pj_vid_"] [data-testid="stPopover"] button{height:44px;border-radius:10px;font-weight:600;
  background:#171D29;border:1px solid var(--line);color:var(--tx);padding:0 .6rem;}
[class*="st-key-pj_card_"] .stButton>button[kind="primary"]{background:var(--blue) !important;border-color:var(--blue) !important;}
[class*="st-key-pj_card_"] .stButton>button[kind="primary"]:hover{background:var(--blue-h) !important;}
[class*="st-key-pj_vid_"] .stButton>button:hover, [class*="st-key-pj_vid_"] .stDownloadButton>button:hover{
  border-color:#3d4d6b;background:#1b2434;}
[class*="st-key-pj_card_"] button, [class*="st-key-pj_vid_"] button{white-space:nowrap;gap:5px;font-size:.88rem;}
[class*="st-key-pj_vid_"] .stButton>button, [class*="st-key-pj_vid_"] .stDownloadButton>button,
[class*="st-key-pj_vid_"] [data-testid="stPopover"] button{padding:0 8px !important;}
button[data-testid="stPopoverButton"] > div:last-child{display:none;}   /* no chevron: reads as a plain "..." */
[class*="st-key-more_"] button{justify-content:flex-end;padding-right:0 !important;}
/* invisible click target over the video thumbnail */
[class*="st-key-pvbig_"]{position:absolute !important;top:16px;left:16px;right:16px;width:auto !important;
  aspect-ratio:16/9;z-index:3;margin:0 !important;}
[class*="st-key-pvbig_"], [class*="st-key-pvbig_"] > div, [class*="st-key-pvbig_"] .stButton{height:100% !important;}
[class*="st-key-pvbig_"] button{width:100%;height:100% !important;min-height:100% !important;opacity:0;cursor:pointer;}
/* empty states */
[class*="st-key-pj_empty_"]{align-items:center;text-align:center;background:var(--card);border:1px dashed var(--line);
  border-radius:14px;padding:34px 16px !important;}
.pj-empty .ic{color:#3a4a66;display:flex;justify-content:center;margin-bottom:6px;}
.pj-empty h3{margin:0;font-size:1.15rem;} .pj-empty p{color:var(--tx2);margin:.25rem 0 .5rem;}
/* skeleton */
.pj-skel{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;}
.pj-skel div{height:250px;border-radius:14px;border:1px solid var(--line);
  background:linear-gradient(100deg,#131924 30%,#1a2230 50%,#131924 70%);background-size:200% 100%;
  animation:pjshine 1.2s linear infinite;}
@keyframes pjshine{to{background-position:-200% 0;}}
/* responsive: 3 -> 2 -> 1 columns, compact nav */
@media (max-width:1100px){
  [class*="st-key-pj_page"] [data-testid="stHorizontalBlock"]:has([class*="st-key-pj_card_"]),
  [class*="st-key-pj_page"] [data-testid="stHorizontalBlock"]:has([class*="st-key-pj_vid_"]){flex-wrap:wrap !important;}
  [class*="st-key-pj_page"] [data-testid="stHorizontalBlock"]:has([class*="st-key-pj_card_"]) > [data-testid="stColumn"],
  [class*="st-key-pj_page"] [data-testid="stHorizontalBlock"]:has([class*="st-key-pj_vid_"]) > [data-testid="stColumn"]{
    min-width:calc(50% - 12px) !important;}
  .pj-skel{grid-template-columns:repeat(2,1fr);}
}
@media (max-width:760px){
  .st-key-pj_nav{padding:0 14px !important;height:auto;min-height:64px;}
  .st-key-pj_nav [data-testid="stHorizontalBlock"]{flex-wrap:wrap;}
  .st-key-pj_page{padding:18px 14px 40px !important;}
  .pj-head h1{font-size:2rem !important;} .pj-deco{display:none;}
  [data-testid="stHorizontalBlock"]{flex-wrap:wrap !important;}
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{min-width:100% !important;}
  .st-key-pj_nav [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{min-width:calc(50% - 8px) !important;}
  .pj-skel{grid-template-columns:1fr;}
}
</style>
"""


def page_css() -> None:
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
