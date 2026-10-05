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
