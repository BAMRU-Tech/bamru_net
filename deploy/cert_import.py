"""
from main.models import Cert
from deploy.cert_import import import_certs
import_certs()
"""
import re
from main.models import Cert, CertSubType, CertType, Member



def import_certs():
    med = CertType.objects.get_or_create(name='Medical')[0]
    med.max_display_length = 9
    med.position = 11
    med.responsive_priority = 10
    med.save()
    med_md = CertSubType.objects.get_or_create(type=med, name='MD', defaults={'position':1})[0]
    med_pa = CertSubType.objects.get_or_create(type=med, name='PA', defaults={'position':2})[0]
    med_rn = CertSubType.objects.get_or_create(type=med, name='RN', defaults={'position':3})[0]
    med_paramedic = CertSubType.objects.get_or_create(type=med, name='Paramedic', defaults={'position':4})[0]
    med_wemt = CertSubType.objects.get_or_create(type=med, name='WEMT', defaults={'position':5})[0]
    med_emt = CertSubType.objects.get_or_create(type=med, name='EMT', defaults={'position':6})[0]
    med_wfr = CertSubType.objects.get_or_create(type=med, name='WFR', defaults={'position':7})[0]
    med_emr = CertSubType.objects.get_or_create(type=med, name='EMR', defaults={'position':8})[0]
    med_wfa = CertSubType.objects.get_or_create(type=med, name='WFA', defaults={'position':9})[0]
    med_fa = CertSubType.objects.get_or_create(type=med, name='FA', defaults={'position':10})[0]
    med_other = CertSubType.objects.get_or_create(type=med, name='Other', defaults={'position':11, 'is_other':True})[0]
    med_o2 = CertSubType.objects.get_or_create(type=med, name='Administer O2', defaults={'position':12})[0]
    med_epi = CertSubType.objects.get_or_create(type=med, name='Epinephrine', defaults={'position':13})[0]

    for c in Cert.objects.filter(type='medical', subtype=None):
        name = c.description
        remap = {
            'WEMT': 'WEMT',
            'W-EMT': 'WEMT',
            'Wilderness EMT': 'WEMT',
            'Emt': 'EMT',
            'Wilderness First Aid': 'WFA',
            'FR': 'FA',  # typo
            'FA Cert' : 'FA',
            'Registered Nurse' : 'RN',
            'Registered Nurse License' : 'RN',
            'Administering Emergency Oxygen': 'Administer O2',
            'Paramedic License': 'Paramedic',
            'PA-C, physician assistant': 'PA',
            'Epinephrine Auto-Injector Cert': 'Epinephrine',
        }
        if name in remap.keys():
            name = remap[name]
        elif re.search('EMT', name):
            name = 'EMT'
        elif re.search('WFR', name) or re.match('Wilderness First Responder', name):
            name = 'WFR'
        elif re.search('WFA', name):
            name = 'WFA'
        elif re.search('first ?aid', name, re.IGNORECASE):
            name = 'FA'
        subtype = CertSubType.objects.filter(type=med, name=name).first()
        if subtype:
            c.subtype = subtype
        else:
            c.subtype = med_other
        c.save()

    cpr = CertType.objects.get_or_create(name='CPR')[0]
    cpr.max_display_length = 6
    cpr.position = 12
    cpr.responsive_priority = 10
    cpr.save()
    cpr_aha = CertSubType.objects.get_or_create(type=cpr, name='AHA BLS', defaults={'position':1})[0]
    cpr_arc = CertSubType.objects.get_or_create(type=cpr, name='ARC BLS', defaults={'position':2})[0]
    cpr_other = CertSubType.objects.get_or_create(type=cpr, name='Other', defaults={'position':3, 'is_other':True})[0]
    for c in Cert.objects.filter(type='cpr', subtype=None):
        c.subtype = cpr_other
        if re.search('BLS', c.description):
            if re.search('AHA', c.description):
                c.subtype = cpr_aha
            elif re.search('(ARC)|(red cross)', c.description, re.IGNORECASE):
                c.subtype = cpr_arc
        c.save()

    ham = CertType.objects.get_or_create(name='HAM')[0]
    ham.max_display_length = 6
    ham.position = 13
    ham.responsive_priority = 10
    ham.has_link = True
    ham.has_file = False
    ham.save()
    ham_other = CertSubType.objects.get_or_create(type=ham, name='HAM', defaults={'position':1, 'is_other':True})[0]
    for c in Cert.objects.filter(type='ham', subtype=None):
        c.subtype = ham_other
        c.save()

    tracking = CertType.objects.get_or_create(name='Tracking')[0]
    tracking.display_name = 'Track'
    tracking.max_display_length = 6
    tracking.position = 14
    tracking.responsive_priority = 12
    tracking.save()
    CertSubType.objects.get_or_create(type=tracking, name='Basic', defaults={'position':1})[0]
    CertSubType.objects.get_or_create(type=tracking, name='Aware', defaults={'position':2})[0]
    tracking_other = CertSubType.objects.get_or_create(type=tracking, name='Other', defaults={'position':3, 'is_other':True})[0]
    for c in Cert.objects.filter(type='tracking', subtype=None):
        name = c.description
        if re.search('Basic Visual Tracking', name) or re.match('Level ?1', name, re.IGNORECASE):
            name = 'Basic'
        subtype = CertSubType.objects.filter(type=tracking, name=name).first()
        if subtype:
            c.subtype = subtype
        else:
            c.subtype = tracking_other
        c.save()

    avalanche = CertType.objects.get_or_create(name='Avalanche')[0]
    avalanche.display_name = 'Avy'
    avalanche.max_display_length = 10
    avalanche.position = 15
    avalanche.responsive_priority = 12
    avalanche.save()
    avalanche_a2 = CertSubType.objects.get_or_create(type=avalanche, name='AIARE 2', defaults={'position':1})[0]
    avalanche_ar = CertSubType.objects.get_or_create(type=avalanche, name='AIARE Rescue', defaults={'position':2})[0]
    avalanche_a1 = CertSubType.objects.get_or_create(type=avalanche, name='AIARE 1', defaults={'position':3})[0]
    avalanche_aaa = CertSubType.objects.get_or_create(type=avalanche, name='AAA 1', defaults={'position':4})[0]
    avalanche_pre = CertSubType.objects.get_or_create(type=avalanche, name='Pre-AIARE', defaults={'position':5})[0]
    avalanche_other = CertSubType.objects.get_or_create(type=avalanche, name='Other', defaults={'position':6, 'is_other':True})[0]
    for c in Cert.objects.filter(type='avalanche', subtype=None):
        name = c.description
        remap = {
            'AAA Level I': 'AAA 1',
            'A3 L1': 'AAA 1',
            'Pre-AAIRE': 'Pre-AIARE',
            'AIARE I': 'AIARE 1',
            'AIARE LVL 1': 'AIARE 1',
            'AIARE Avalanche Rescue': 'AIARE Rescue',
        }
        if name in remap.keys():
            name = remap[name]
        subtype = CertSubType.objects.filter(type=avalanche, name=name).first()
        if subtype:
            c.subtype = subtype
        else:
            c.subtype = avalanche_other
        c.save()

    rigging = CertType.objects.get_or_create(name='Rigging')[0]
    rigging.max_display_length = 8
    rigging.position = 16
    rigging.responsive_priority = 12
    rigging.save()
    CertSubType.objects.get_or_create(type=rigging, name='RFR ST', defaults={'position':1})[0]
    CertSubType.objects.get_or_create(type=rigging, name='RFR', defaults={'position':2})[0]
    CertSubType.objects.get_or_create(type=rigging, name='RS1', defaults={'position':3})[0]
    rigging_other = CertSubType.objects.get_or_create(type=rigging, name='Other', defaults={'position':4, 'is_other':True})[0]
    for c in Cert.objects.filter(type='rigging', subtype=None):
        name = c.description
        remap = {
            'RFR Fundamentals': 'RFR',
            'RFR Specialty Techniques': 'RFR ST',
            'Rigging for Rescue - Rope Rescue I': 'RFR',
        }
        if name in remap.keys():
            name = remap[name]
        subtype = CertSubType.objects.filter(type=rigging, name=name).first()
        if subtype:
            c.subtype = subtype
        else:
            c.subtype = rigging_other
        c.save()

    ics = CertType.objects.get_or_create(name='ICS')[0]
    ics.position = 17
    ics.responsive_priority = 19
    ics.has_expiration_date = False
    ics.show_combined = True
    ics.save()
    CertSubType.objects.get_or_create(type=ics, name='003', defaults={'position':1})[0]
    CertSubType.objects.get_or_create(type=ics, name='100', defaults={'position':2})[0]
    CertSubType.objects.get_or_create(type=ics, name='200', defaults={'position':3})[0]
    CertSubType.objects.get_or_create(type=ics, name='230', defaults={'position':4})[0]
    CertSubType.objects.get_or_create(type=ics, name='300', defaults={'position':5})[0]
    CertSubType.objects.get_or_create(type=ics, name='400', defaults={'position':6})[0]
    CertSubType.objects.get_or_create(type=ics, name='700', defaults={'position':7})[0]
    CertSubType.objects.get_or_create(type=ics, name='800', defaults={'position':8})[0]
    ics_other = CertSubType.objects.get_or_create(type=ics, name='Other', defaults={'position':9, 'is_other':True})[0]
    for c in Cert.objects.filter(type='ics', subtype=None):
        name = c.description
        name = re.sub('^ICS[ -]?', '', name)  # strip ICS- from start
        name = re.sub(' ?[A-Za-z]$', '', name)  # strip letter off end
        subtype = CertSubType.objects.filter(type=ics, name=name).first()
        if subtype:
            c.subtype = subtype
        else:
            c.subtype = ics_other
        c.save()

    overhead = CertType.objects.get_or_create(name='Overhead')[0]
    overhead.max_display_length = 8
    overhead.position = 18
    overhead.responsive_priority = 14
    overhead.save()
    CertSubType.objects.get_or_create(type=overhead, name='BASARC', defaults={'position':1})[0]
    CertSubType.objects.get_or_create(type=overhead, name='NASAR', defaults={'position':2})[0]
    CertSubType.objects.get_or_create(type=overhead, name='D&C', defaults={'position':3})[0]
    CertSubType.objects.get_or_create(type=overhead, name='NPS', defaults={'position':4})[0]
    overhead_other = CertSubType.objects.get_or_create(type=overhead, name='Other', defaults={'position':5, 'is_other':True})[0]
    for c in Cert.objects.filter(type='overhead', subtype=None):
        name = c.description
        remap = {
            'Winter D&C': 'D&C',
            'D&C Search Function': 'D&C',
            'BASARC MLPI': 'BASARC',
            'BASARC-MLPI': 'BASARC',
        }
        if name in remap.keys():
            name = remap[name]
        subtype = CertSubType.objects.filter(type=overhead, name=name).first()
        if subtype:
            c.subtype = subtype
        else:
            c.subtype = overhead_other
        c.save()

    so = CertType.objects.get_or_create(name='SO')[0]
    so.template = """
{%- if 'OL' in roles -%}
OL
{%- elif certs -%}
Bkg
{%- endif -%}
"""
    so.position = 2;
    so.responsive_priority = 2
    so.has_file = False
    so.save()
    so_bk = CertSubType.objects.get_or_create(type=so, name='Background', defaults={'position':2})[0]
    so_v = CertSubType.objects.get_or_create(type=so, name='V number', defaults={'position':1, 'is_other':True})[0]
    for c in Cert.objects.filter(type='background'):
        if re.match('V', c.description):
            c.subtype = so_v
        else:
            c.subtype = so_bk
        c.save()


    driver = CertType.objects.get_or_create(name='Driver')[0]
    driver.template = """
{%- if all_certs.SO and
("Combination (old)" is valid_subtype_in(certs) or
 ("Classroom" is valid_subtype_in(certs) and "Practical" is valid_subtype_in(certs))) -%}
SO
{%- elif "Combination (old)" is valid_subtype_in(certs) or
 ("Classroom" is valid_subtype_in(certs) and "Practical" is valid_subtype_in(certs)) or
 "Gerald Only" is valid_subtype_in(certs) -%}
Gerald
{%- endif -%}
"""
    driver.display_name = 'Drive'
    driver.position = 3;
    driver.responsive_priority = 2
    driver.has_file = False
    driver.save()
    driver_class = CertSubType.objects.get_or_create(type=driver, name='Classroom', defaults={'position':1})[0]
    driver_prac = CertSubType.objects.get_or_create(type=driver, name='Practical', defaults={'position':2})[0]
    driver_g = CertSubType.objects.get_or_create(type=driver, name='Gerald Only', defaults={'position':3})[0]
    driver_old = CertSubType.objects.get_or_create(type=driver, name='Combination (old)', defaults={'position':4})[0]
    for c in Cert.objects.filter(type='driver'):
        c.subtype = driver_old
        c.save()

    e = CertType.objects.get_or_create(name='Endorsements')[0]
    e.template = """
{%- if "TM" is valid_subtype_in(certs) -%}
TM
{%- elif "FM" is valid_subtype_in(certs) -%}
FM
{%- if "Wilderness Search" is valid_subtype_in(certs) -%}
, WS
{%- endif -%}
{%- if "Snow & Ice" is valid_subtype_in(certs) -%}
, SI
{%- endif -%}
{%- if "Tech Rock" is valid_subtype_in(certs) -%}
, TR
{%- endif -%}
{%- elif "T" is valid_subtype_in(certs) -%}
T
{%- endif -%}
"""
    e.display_name = 'Endr'
    e.has_expiration_date = False
    e.position = 4;
    e.responsive_priority = 5
    e.has_file = False
    e.save()
    e_tm = CertSubType.objects.get_or_create(type=e, name='TM', defaults={'position':1})[0]
    e_ws = CertSubType.objects.get_or_create(type=e, name='Wilderness Search', defaults={'position':2})[0]
    e_si = CertSubType.objects.get_or_create(type=e, name='Snow & Ice', defaults={'position':3})[0]
    e_tr = CertSubType.objects.get_or_create(type=e, name='Tech Rock', defaults={'position':4})[0]
    e_fm = CertSubType.objects.get_or_create(type=e, name='FM', defaults={'position':5})[0]
    e_t = CertSubType.objects.get_or_create(type=e, name='T', defaults={'position':6})[0]

    for m in Member.members.all():
        if m.status == 'TM':
            Cert.objects.get_or_create(subtype=e_tm, member=m)
            Cert.objects.get_or_create(subtype=e_ws, member=m)
            Cert.objects.get_or_create(subtype=e_si, member=m)
            Cert.objects.get_or_create(subtype=e_tr, member=m)
            Cert.objects.get_or_create(subtype=e_fm, member=m)
            Cert.objects.get_or_create(subtype=e_t, member=m)
        if m.status == 'FM':
            Cert.objects.get_or_create(subtype=e_fm, member=m)
            Cert.objects.get_or_create(subtype=e_t, member=m)
        if m.status == 'T' or m.status == 'R' or m.status == 'S':
            Cert.objects.get_or_create(subtype=e_t, member=m)

    callout = CertType.objects.get_or_create(name='Callout')[0]
    callout.template = """
{%- if ('AHA BLS' is valid_subtype_in(all_certs.CPR) or 
          'ARC BLS' is valid_subtype_in(all_certs.CPR)) and
all_certs.Medical is valid
-%}
Y
{%- endif -%}
"""
    callout.position = 1;
    callout.responsive_priority = 2
    callout.display_only = True
    callout.save()
