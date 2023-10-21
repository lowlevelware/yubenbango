import csv
import json
import re
import sqlite3

import cutlet
import mojimoji

translate = cutlet.Cutlet()

# original data README:
# https://www.post.japanpost.jp/zipcode/dl/readme.html

FIELDS = ['jisx0402',  # 全国地方公共団体コード
          'old_code',  # old 3-digit codes
          'postal_code', 'prefecture_kana', 'city_kana', 'district_kana', 'prefecture', 'city', 'district',
          'partial', # Does this district have more than one code?
          'koazabanchi',  # Are banchi given for each koaza?
          'chome',  # Are chome used?
          'multi',  # Is there more than one district in this code?
          'update_status',  # 「0」は変更なし、「1」は変更あり、「2」廃止（廃止データのみ使用）
          'update_reason'  # 0-6
          ]

# Readme for jigyousho:
# https://www.post.japanpost.jp/zipcode/dl/jigyosyo/readme.html

JIGYOU_FIELDS = ['jis',  # some kind of jis code - README doesn't say which type
                 'kana',  # kana of business name
                 'name',  # business name
                 'prefecture', 'city', 'district',
                 'banchi',  # like 1丁目3-2
                 'postal_code',  # actual postal code
                 'old_code', 'post_office',  # 取扱局
                 'type',  # 0 = large office, 1 = po box
                 'multiple',  # 0 = no, 1 = first of multi, 2 = 2 of multi, 3 = 3 of multi (no higher vals?)
                 'correction',  # 0 = no correction, 1 = newly added, 5 = removed
                 ]

PARTS = ('prefecture', 'city', 'district')
STATUS = ('変更なし', '変更あり', '廃止')
REASON = ('変更なし', '市政・区政・町政・分区・政令指定都市施行', '住居表示の実施', '区画整理', '郵便区調整等', '訂正', '廃止')
NOTE_REGEX = '([^（]*)(（.*）?)?'


def build_json(ken_all, jigyousho):
    data = {}

    multiline = False
    multiline_district = False  # multiline district
    multiline_kana = False  # kana

    # Residential areas
    with open(ken_all) as csvfile:
        reader = csv.DictReader(csvfile, FIELDS)
        for row in reader:
            code = row['postal_code']
            # defaults
            row['multiline'] = False
            row['alternates'] = []
            row['note'] = None

            if multiline:
                multiline_district += row['district']
                multiline_kana += row['district_kana']
                if '）' in row['district']:
                    multiline = False
                    row['district'] = multiline_district
                    row['district_kana'] = multiline_kana
                    row['multiline'] = True
                    multiline_district = False
                    multiline_kana = False
                else:
                    continue

            # handle long name nonsense
            # technically, if the district name is >38 full width chars,
            # another line is added and all other fields are copied. However,
            # where the line break is inserted seems random. The only sign is
            # open parens. Common in areas in Kyoto that use the
            # intersection-relative addressing system.

            if '（' in row['district'] and '）' not in row['district']:
                multiline = True
                multiline_district = row['district']
                multiline_kana = row['district_kana']
                continue

            # fix special case
            # only occurs in format:
            # （高層棟）（XX階）
            # and only in one place...
            row['district'] = row['district'].replace('）（', '')

            # handle notes
            district, note = re.search(NOTE_REGEX, row['district']).groups()
            if note:
                row['district'] = district
                row['note'] = note[1:-1]  # trim parens
                row['note'] = mojimoji.zen_to_han(row['note'], kana=False)  # no zengaku :P
                # don't need kana for note
                row['district_kana'] = re.sub('\(.*\)?', '', row['district_kana'])

            # fix hankaku
            for field in PARTS:
                key = field + '_kana'
                row[key] = mojimoji.han_to_zen(row[key])

            # handle flags
            row['partial'] = int(row['partial']) == 1
            row['koazabanchi'] = int(row['koazabanchi']) == 1
            row['chome'] = int(row['chome']) == 1
            row['multi'] = int(row['multi']) == 1
            row['update_status'] = STATUS[int(row['update_status'])]
            row['update_reason'] = REASON[int(row['update_reason'])]

            # move junk to notes
            if row['district'] == '以下に掲載がない場合':
                row['district'] = ''
                row['district_kana'] = ''
                row['note'] = '以下に掲載がない場合'

            # more junk
            # Iwateken has 地割 which are usually not parenthesized but are unhelpful.
            if '地割' in row['district']:
                district, note = re.search('([^第]*)(第?[０-９]+地割.*)', row['district']).groups()
                row['district'] = district
                if row['note']:
                    # sometimes there are parentheticals after the 地割 note
                    row['note'] = note + '(' + row['note'] + ')'
                else:
                    row['note'] = note
                row['district_kana'] = re.sub('[０-９].*', '', row['district_kana'])
                if note[0] == '第':
                    # cut off the ダイ if necessary
                    row['district_kana'] = row['district_kana'][:-2]

            # more junk
            # Some districts look like "XXの次に番地がくる場合"
            if '次に番地' in row['district']:
                row['district'] = row['district'][:-10]
                row['district_kana'] = row['district_kana'][:-13]

            # more junk
            # "一円" is used after some district names to indicate the
            # surrounding area is included. However, 一円 is also a place name
            # in exactly one place (5220317). Where it is not part of the place name,
            # this removes it since it's not even a meaningful note.
            if row['district'][-2:] == '一円' and row['district'] != '一円':
                row['district'] = row['district'][:-2]
                row['district_kana'] = row['district_kana'][:-4]

            # finally, if this is for an area with an entry already, add an alternate
            # note that unlike long rows, alternates are not always sequential.
            if code in data:
                data[code]['alternates'].append(row)
                continue
            data[code] = row

    # Commercial and Business areas
    with open(jigyousho) as csvfile:
        reader = csv.DictReader(csvfile, JIGYOU_FIELDS)
        for row in reader:
            info = {}
            # copy most keys over
            for key in 'jis kana name prefecture city district banchi postal_code old_code post_office'.split():
                info[key] = row[key]

            # fix kana and banchi
            for field in ('kana', 'banchi'):
                # First make sure kana are full width
                info[field] = mojimoji.han_to_zen(info[field])
                # then convert numbers/ascii to half width
                info[field] = mojimoji.zen_to_han(info[field], kana=False)

            # remaining keys get special treatment

            # pobox or office
            variety = int(row['type'])
            assert variety in (0, 1), "Unexpected value for type, should be 0 or 1"
            info['type'] = 'box' if variety == 1 else 'office'

            # actual number seems meaningless
            info['multiple'] = False if row['multiple'] == '0' else True

            # new status. 5 is also possible but shouldn't be in the file we're checking.
            status = int(row['correction'])
            assert status in (0, 1), "Unexpected correction status, should be 0 or 1"
            info['new'] = True if status == 1 else False

            # Get readings if available (should always be available)
            # readings = get_cached_kana(db, kana_cache, info['prefecture'],
            #        info['city'], info['district'])
            key = (info['prefecture'], info['city'], info['district'])
            readings = data.get(key, ("", "", ""))

            info['prefecture_kana'] = readings[0]
            info['city_kana'] = readings[1]
            info['district_kana'] = readings[2]
            # Ensure alternates is set to avoid issues with instantiating the OfficeCodeBase named tuple.
            info.setdefault('alternates', [])

            code = info['postal_code']
            if code in data:
                data[code]['alternates'].append(info)
            else:
                data[code] = info

    with open('data/yubenbango.json', 'w') as outfile:
        outfile.write(json.dumps(data, ensure_ascii=False, indent=2))

    # write all postal data to sqlite db
    conn = sqlite3.connect('data/yubenbango.sqlite')
    db = conn.cursor()

    db.execute("""drop table if exists jurisdiction""")
    db.execute("""
        create table jurisdiction
        (
            code       text,
            prefecture text,
            todofuken  text,
            data       text
        )
    """)
    db.execute("""create index jurisdiction_index on jurisdiction (code)""")

    for key, val in data.items():
        entry = json.dumps(val, ensure_ascii=False)
        # add additional columns for querying
        prefecture = val['prefecture']
        todofuken = translate.romaji(prefecture)
        db.execute("insert into jurisdiction(code, prefecture, todofuken, data) values (?, ?, ?, ?)",
                   (key, prefecture, todofuken, entry))

    conn.commit()

    # Execute a query to fetch the data from the new_table
    db.execute("select code, prefecture, todofuken from jurisdiction")
    data = db.fetchall()

    # Define the CSV file name
    jurisdiction_csv_file = 'data/jurisdictions.csv'

    # Write the data to a CSV file
    with open(jurisdiction_csv_file, 'w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['code', 'prefecture', 'todofuken'])  # Write header row
        csv_writer.writerows(data)

    conn.close()


if __name__ == '__main__':
    build_json('raw/ken_all.utf8.csv', 'raw/jigyousho.utf8.csv')
