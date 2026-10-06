import xml.etree.ElementTree as ET

from sportscode_extract.timing import check, interval
from sportscode_extract.export_xml import labels, write_xml


def test_decimal_arithmetic_and_invalid_bounds():
    assert str(interval({'startTimeOffset':0.1,'startTime':0.1,'endTime':0.3})[1])=='0.3'
    clip={'startTimeOffset':-0.1,'startTime':0,'endTime':1}
    assert check(clip,0.9)['timing_status']=='timing_unresolved'
    assert check({'startTimeOffset':0,'startTime':2,'endTime':1},1)['timing_status']=='timing_unresolved'


def test_override_is_explicit_not_media_verified():
    clip={'startTimeOffset':0,'startTime':0,'endTime':2}
    assert check(clip,1)['timing_status']=='timing_unresolved'
    result=check(clip,1,override={'local_start':0.1,'local_end':0.9})
    assert result['timing_status']=='resolved'
    assert result['timing_confidence']=='explicit-policy'
    assert check(clip,1,override={'local_start':0,'local_end':5})['timing_status']=='timing_unresolved'


def test_labels_distinct_notes_values_and_provenance():
    clip={'id':'uuid','startTime':10,'endTime':11,'description':'Description','moment':{'note':'Note','tags':[{'key':'Key','value':'Value'},{'key':'Only','value':''}]}}
    normal=labels(clip,'Code',1)
    assert ('Key','Value') in normal
    assert ('Tag','Only') in normal
    assert normal.count(('Note','Note'))==1
    assert normal.count(('Note','Description'))==1
    assert not any(group=='Clip UUID' for group,text in normal)
    assert ('Clip UUID','uuid') in labels(clip,'Code',1,True)


def test_xml_original_code_and_distinct_colors(tmp_path):
    occurrences=[{'position':i+1,'group':{'name':f'group{i}','color':color},'clip':{'id':str(i),'originalGroupName':f'original{i}','startTime':0,'endTime':1}} for i,color in enumerate(['#000000','#520001'])]
    path=tmp_path/'output.xml'
    assert write_xml(path,occurrences,[(0,1),(1,2)],code_from='original')=='group colors'
    root=ET.parse(path)
    assert [n.text for n in root.findall('./ALL_INSTANCES/instance/code')]==['original0','original1']
    assert [n.text for n in root.findall('./rows/row/R')]==['0','82']


def test_focus_xml_free_text_and_16_bit_rows(tmp_path):
    clip={'id':'0','startTime':0,'endTime':1,'description':'Same','moment':{'note':'Same','tags':[{'key':'CPA','value':''}]}}
    occurrences=[{'position':1,'group':{'name':'Goal','color':'#466EB4'},'clip':clip}]
    path=tmp_path/'focus.xml'
    write_xml(path,occurrences,[(0,1)],target='focus')
    root=ET.parse(path)
    instance=root.find('./ALL_INSTANCES/instance')
    assert instance.findtext('free_text')=='Same'
    assert [(n.findtext('group'),n.findtext('text')) for n in instance.findall('label')]==[('Tag','CPA')]
    assert root.find('./rows/row/Code') is None
    assert root.findtext('./rows/row/code')=='Goal'
    assert [root.findtext(f'./rows/row/{k}') for k in ('R','G','B')]==[str(0x46*257),str(0x6E*257),str(0xB4*257)]


def test_angles_xml_has_no_free_text(tmp_path):
    clip={'id':'0','startTime':0,'endTime':1,'description':'Note'}
    path=tmp_path/'angles.xml'
    write_xml(path,[{'position':1,'group':{'name':'Goal'},'clip':clip}],[(0,1)])
    assert ET.parse(path).find('./ALL_INSTANCES/instance/free_text') is None


def test_lenient_timing_keeps_mismatched_clips():
    clip={'startTimeOffset':0.5,'startTime':0,'endTime':2}
    assert check(clip,4)['timing_status']=='timing_unresolved'
    longer=check(clip,4,lenient=True)
    assert (longer['timing_status'],longer['timing_confidence'],longer['local_end'])==('resolved','lenient',2.5)
    shorter=check(clip,1.5,lenient=True)
    assert (shorter['timing_status'],shorter['local_start'],shorter['local_end'])==('resolved',0.5,1.5)
    assert 'clamped' in shorter['timing_rule']
    assert check(clip,0.4,lenient=True)['timing_status']=='timing_unresolved'
    assert check({'startTimeOffset':-0.1,'startTime':0,'endTime':1},2,lenient=True)['timing_status']=='timing_unresolved'
    assert check(clip,2.5,lenient=True)['timing_confidence']=='media-consistent'
