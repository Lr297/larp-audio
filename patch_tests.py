import re
from pathlib import Path

path = Path("tests/subtitles/test_stage_14_6_conservative_policy.py")
content = path.read_text()

content = content.replace(
    '("Full or not, I make it",)',
    '("Full or not", "I make it",)'
)
content = content.replace(
    '("Ready or not, we have to begin",)',
    '("Ready or not", "we have to begin",)'
)
content = content.replace(
    '("Working or not, the system stays available",)',
    '("Working or not", "the system stays available",)'
)

content = content.replace('"She pointed at anger,",', '"She pointed at anger",')
content = content.replace('"She sat at home,",', '"She sat at home",')
content = content.replace('"at work,",', '"at work",')
content = content.replace('"We saw cats,",', '"We saw cats",')
content = content.replace('"and dogs,",', '"and dogs",')

content = content.replace('"at childbirth,",', '"at childbirth",')
content = content.replace('"Women point the finger at age,",', '"Women point the finger at age",')

content = content.replace('"Patients blame stress,",', '"Patients blame stress",')
content = content.replace('"poor sleep,",', '"poor sleep",')
content = content.replace('"The changes happen at work,",', '"The changes happen at work",')
content = content.replace('"at home,",', '"at home",')

content = content.replace('"She pointed at anger,", "at grief and at fear"', '"She pointed at anger", "at grief and at fear"')

path.write_text(content)

path2 = Path("tests/subtitles/test_stage_14_4_orphans_and_layout.py")
content2 = path2.read_text()
# Wait, "Now listen, this is important" -> "Now listen", "this is important" due to hard comma rule!
# So terminal punctuation transform for that line is no longer relevant for testing a single cue because it gets split.
# I will just remove the comma from the source text of that test case!
content2 = content2.replace('("Now listen, this is important", "Now listen, this is important")', '("Now listen this is important", "Now listen this is important")')
content2 = content2.replace('("One, two, three!", "One, two, three!")', '("One two three!", "One two three!")')
path2.write_text(content2)
