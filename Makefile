
all: data/yubenbango.sqlite

start:
	[ -d raw ] || mkdir raw
	[ -d data ] || mkdir data

clean:
	rm raw/*
	rm data/*

raw/ken_all.zip:
	wget -O raw/ken_all.zip 'https://www.post.japanpost.jp/zipcode/dl/kogaki/zip/ken_all.zip'

raw/ken_all.utf8.csv: raw/ken_all.zip
	cd raw; \
	unzip -o ken_all.zip
	iconv -f sjis -t utf8 raw/KEN_ALL.CSV > raw/ken_all.utf8.csv

raw/jigyosyo.zip:
	wget -O raw/jigyosyo.zip 'https://www.post.japanpost.jp/zipcode/dl/jigyosyo/zip/jigyosyo.zip'

raw/jigyousho.utf8.csv: raw/jigyosyo.zip
	cd raw; \
	unzip -o jigyosyo.zip
	iconv -f cp932 -t utf8 raw/JIGYOSYO.CSV > raw/jigyousho.utf8.csv

data/yubenbango.sqlite: start raw/ken_all.utf8.csv raw/jigyousho.utf8.csv
	python main.py