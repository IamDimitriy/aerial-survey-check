"""Ограниченный пример: текст ТЗ → кандидаты правил → свойства реального GeoTIFF.

Не геодезическая приёмка. Кандидаты правил требуют подтверждения специалистом.
"""
import hashlib
import json
import re
from pathlib import Path
from time import perf_counter

BASE = Path(__file__).resolve().parent
import rasterio
from pypdf import PdfReader


def extract(pdf):
    pages = [' '.join((p.extract_text() or '').split()) for p in PdfReader(pdf).pages]
    specs = [
        ('crs', 1, r'системе координат WGS-84', 'all', 'WGS-84', '7'),
        ('format', 2, r'2\.2\. В формате GeoTIFF', 'orthophoto', 'GeoTIFF', '8 / 2.2'),
        ('pixel_visible', 2, r'видимом диапазоне создаются с разрешением не хуже (\d+) см/пиксель', 'visible', 0.05, '8 / 2.3'),
        ('pixel_spectral', 2, r'спектрозональные создаются с разрешением не хуже (\d+) см/пиксель', 'spectral', 0.20, '8 / 2.4'),
        ('channels_spectral', 3, r'GeoTIFF,\s*(\d+)-\s*канальный', 'spectral', 5, '11'),
        ('plan_accuracy', 2, r'не хуже 1 м', 'orthophoto', 'specialist', '8 / 2.1'),
    ]
    result = []
    for key, page, pattern, scope, value, section in specs:
        m = re.search(pattern, pages[page-1], re.I)
        if not m:
            raise ValueError(f'Не найдено правило {key}, нельзя подставить готовое требование')
        if key.startswith('pixel_'):
            value = int(m[1]) / 100
        elif key == 'channels_spectral':
            value = int(m[1])
        result.append(dict(id=key, page=page, section=section, scope=scope,
                           value=value, confirmation='candidate; specialist confirmation pending'))
    return result


def classify(facts, role):
    geotiff = facts['driver'] == 'GTiff' and facts['epsg'] is not None
    crs = 'pass' if facts['epsg'] == 4326 else ('manual' if facts['epsg'] is None else 'fail')
    checks = [dict(id='format', status='pass' if geotiff else 'fail', detail='GTiff + CRS'),
              dict(id='crs', status=crs, detail=f"EPSG:{facts['epsg']}; target WGS-84 / EPSG:4326")]
    if role == 'visible':
        if facts['units'] != 'metre':
            status, detail = 'manual', 'Пиксель в градусах: прямое сравнение с 0.05 м запрещено'
        else:
            status = 'pass' if max(facts['pixel_size']) <= 0.05 else 'fail'
            detail = 'Сравнивается только размер сетки; точность на местности не измерена'
        checks.append(dict(id='pixel_visible', status=status, detail=detail))
        checks.append(dict(id='channels_spectral', status='not_applicable', detail='Образец назначен видимому ортофото, правило пяти каналов относится к спектрозональному'))
    else:
        raise ValueError('Для примера поддержана только явно назначенная роль visible')
    checks.append(dict(id='plan_accuracy', status='manual', detail='Нужны контрольные точки и специалист; заголовок TIFF не подтверждает СКО'))
    return checks


def run():
    started = perf_counter()
    pdf = BASE / 'istochniki/tz-vinograd-2023.pdf'
    tif = BASE / 'istochniki/oam-uav.tif'
    rules = extract(pdf)
    with rasterio.open(tif) as ds:
        # Девять окон доказывают чтение выборки, а не всех пикселей файла.
        windows = []
        for y in (0, ds.height//2, ds.height-32):
            for x in (0, ds.width//2, ds.width-32):
                data = ds.read(window=((y,y+32),(x,x+32)))
                assert data.shape == (ds.count,32,32)
                windows.append(dict(x=x,y=y,shape=list(data.shape)))
        facts = dict(driver=ds.driver,width=ds.width,height=ds.height,channels=ds.count,
                     epsg=ds.crs.to_epsg() if ds.crs else None,
                     units='degree' if ds.crs and ds.crs.is_geographic else
                     (ds.crs.linear_units if ds.crs else None),
                     pixel_size=list(ds.res),dtypes=list(ds.dtypes),read_windows=windows)
    checks = classify(facts,'visible')
    manifest = dict(sample_role='visible orthophoto; assigned for this example by Codex',
                    relation_to_tz='Independent public UAV sample, not delivery for this contract',
                    author='Santiago Pastor', license='CC BY 4.0', provider='OpenAerialMap / Open Imagery Network',
                    urls=['https://rvwa.ru/images/07e7/04/0c/514017.pdf',
                          'https://api.openaerialmap.org/meta/59e62b863d6412ef72209ae1',
                          'https://oin-hotosm-temp.s3.amazonaws.com/573a17d4cd0663bb003c32b6/0/575fcf142b67227a79b4fbfd.tif'],
                    files={f.name:dict(bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in (pdf,tif)})
    # Наличие разных видов продукции определяется манифестом, не расширением .tif.
    inventory = [{'role':'visible','file':tif.name,'status':'present'}]
    for role in ('spectral','height_map','field_shp','ndvi','vineyard_kml','area_report_xls','pdtk_conclusion','work_report'):
        inventory.append(dict(role=role,file=None,status='missing_in_demo_package'))
    out = BASE / 'rezultaty-vinograd'
    out.mkdir(exist_ok=True)
    report = dict(requirements=rules,facts=facts,checks=checks,inventory=inventory,manifest=manifest)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# Проверка открытого GeoTIFF по ТЗ виноградарей','',
           'Кандидаты правил извлечены из текстового PDF. Специалист ещё не подтвердил чек-лист. Это демонстрация проверки свойств, не приёмка заказа.','',
           '| Проверка | Статус | Пояснение |','|---|---|---|']
    lines += [f"| {c['id']} | {c['status']} | {c['detail']} |" for c in checks]
    lines += ['',f"Растр: {facts['width']} × {facts['height']}, каналов {facts['channels']}, EPSG:{facts['epsg']}. Размер пикселя {facts['pixel_size']} {facts['units']}.",
              'Прочитано девять окон 32×32, полная декодировка всех пикселей не проверялась.',
              'В демонстрационной папке отсутствуют остальные восемь позиций сдачи. Это не недостатки реального подрядчика: образец не относится к этому ТЗ.',
              '', 'Точное происхождение, SHA-256, правила со страницами и инвентаризация — report.json.']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Контроль главных ошибок решения на явно искусственных метаданных.
    assert next(c for c in checks if c['id']=='pixel_visible')['status']=='manual'
    assert next(c for c in checks if c['id']=='channels_spectral')['status']=='not_applicable'
    wrong = dict(facts,epsg=3857)
    assert next(c for c in classify(wrong,'visible') if c['id']=='crs')['status']=='fail'
    fine = dict(facts,units='metre',pixel_size=[0.04,0.04])
    coarse = dict(facts,units='metre',pixel_size=[0.1,0.1])
    assert next(c for c in classify(fine,'visible') if c['id']=='pixel_visible')['status']=='pass'
    assert next(c for c in classify(coarse,'visible') if c['id']=='pixel_visible')['status']=='fail'
    print(json.dumps({'rules':len(rules),'checks':checks,'elapsed_s':perf_counter()-started},ensure_ascii=False))


if __name__ == '__main__':
    run()
