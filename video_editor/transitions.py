"""Transition types FFmpeg's xfade can do. The frontend (lib/styles.ts TRANSITIONS) lists the same ids."""

TRANSITION_TYPES = (
    "fade", "fadeblack", "fadewhite", "fadegrays", "fadefast", "fadeslow", "dissolve", "pixelize", "hblur",
    "wipeleft", "wiperight", "wipeup", "wipedown", "wipetl", "wipetr", "wipebl", "wipebr",
    "slideleft", "slideright", "slideup", "slidedown", "smoothleft", "smoothright", "smoothup", "smoothdown",
    "coverleft", "coverright", "coverup", "coverdown", "revealleft", "revealright", "revealup", "revealdown",
    "circleopen", "circleclose", "circlecrop", "rectcrop", "radial", "zoomin", "squeezeh", "squeezev",
    "vertopen", "vertclose", "horzopen", "horzclose", "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice", "hlwind", "hrwind", "vuwind", "vdwind",
)
