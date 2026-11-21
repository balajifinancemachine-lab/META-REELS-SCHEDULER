import urllib.request
import urllib.parse
import json
import sys
from pathlib import Path

# Add local path and ensure API server is running
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import meta_reels_scheduler as mrs

def test_api():
    base = 'http://127.0.0.1:8765'
    
    # Ensure server is active
    mrs.ensure_api_server_running()

    # 1. Status
    res = urllib.request.urlopen(f'{base}/api/status')
    status = json.loads(res.read().decode('utf-8'))
    assert status['pages_count'] >= 1, 'Pages count mismatch'
    print(f'[LIVE TEST 1] Status endpoint OK - {status["pages_count"]} pages configured in active brand.')
    
    # 2. Profiles
    res = urllib.request.urlopen(f'{base}/api/profiles')
    profs = json.loads(res.read().decode('utf-8'))
    total_profs = len(profs['profiles'])
    assert total_profs > 0, 'No profiles found'
    print(f'[LIVE TEST 2] Profiles endpoint OK - {total_profs} profiles detected.')
    
    # 3. Extension Sync
    req = urllib.request.Request(f'{base}/api/extension/sync', data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    sync_res = json.loads(res.read().decode('utf-8'))
    assert sync_res['ok'], 'Extension sync failed'
    print('[LIVE TEST 3] Extension auto-sync endpoint OK.')
    
    # 4. Schedule CRUD
    # Create
    new_sched = {
        'name': 'Live Test Interval Schedule',
        'time': '18:00',
        'repeat_interval_minutes': 45,
        'repeat_duration_hours': 6,
        'enabled': True
    }
    req = urllib.request.Request(f'{base}/api/schedules/create', data=json.dumps(new_sched).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    created = json.loads(res.read().decode('utf-8'))
    assert created['ok'], 'Schedule creation failed'
    sid = created['schedule']['id']
    print(f'[LIVE TEST 4a] Schedule created OK: {sid}')
    
    # Update
    update_data = {
        'id': sid,
        'name': 'Live Test Interval Schedule (Updated)',
        'time': '18:30',
        'repeat_interval_minutes': 60,
        'repeat_duration_hours': 8,
        'enabled': True
    }
    req = urllib.request.Request(f'{base}/api/schedules/update', data=json.dumps(update_data).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    updated = json.loads(res.read().decode('utf-8'))
    assert updated['ok'], 'Schedule update failed'
    print(f'[LIVE TEST 4b] Schedule updated OK: {sid}')
    
    # Delete
    del_data = {'id': sid}
    req = urllib.request.Request(f'{base}/api/schedules/delete', data=json.dumps(del_data).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    deleted = json.loads(res.read().decode('utf-8'))
    assert deleted['ok'], 'Schedule delete failed'
    print(f'[LIVE TEST 4c] Schedule deleted OK: {sid}')
    
    # 5. Profile Switch
    switch_data = {'profile': 'Profile 15'}
    req = urllib.request.Request(f'{base}/api/profile/select', data=json.dumps(switch_data).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    switched = json.loads(res.read().decode('utf-8'))
    assert switched['ok'], 'Profile switch failed'
    sel_prof = switched['selected_profile']
    print(f'[LIVE TEST 5] Profile select endpoint OK: {sel_prof}')
    
    # 6. Next Task Endpoint
    res = urllib.request.urlopen(f'{base}/next-task?page_id=1021342791059139')
    task_res = json.loads(res.read().decode('utf-8'))
    assert 'task' in task_res, 'next-task failed'
    print('[LIVE TEST 6] next-task endpoint OK.')
    
    # 7. Logs Endpoint
    res = urllib.request.urlopen(f'{base}/api/logs')
    logs_res = json.loads(res.read().decode('utf-8'))
    assert logs_res['ok'] and len(logs_res['logs']) > 0, 'Logs endpoint failed'
    total_logs = len(logs_res['logs'])
    print(f'[LIVE TEST 7] Logs endpoint OK - {total_logs} log entries.')

    # 8. Brands List & Active Brand
    res = urllib.request.urlopen(f'{base}/api/brands')
    brands_data = json.loads(res.read().decode('utf-8'))
    assert brands_data['ok'] and len(brands_data['brands']) > 0, 'Brands endpoint failed'
    orig_bid = brands_data['active_brand_id']
    print(f'[LIVE TEST 8] Brands endpoint OK - {len(brands_data["brands"])} brand(s) detected, active: {orig_bid}.')

    # 9. Brand Create & Select
    brand_payload = {
        'name': 'Live Test Brand',
        'chrome_profile': 'Profile 15',
        'video': '',
        'location': 'Mumbai',
        'caption': 'Live brand test caption',
        'auto_publish': True
    }
    req = urllib.request.Request(f'{base}/api/brands/create', data=json.dumps(brand_payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    brand_created = json.loads(res.read().decode('utf-8'))
    assert brand_created['ok'], 'Brand create failed'
    new_bid = brand_created['brand']['id']
    print(f'[LIVE TEST 9a] Brand created OK: {new_bid}')

    req = urllib.request.Request(f'{base}/api/brands/select', data=json.dumps({'brand_id': new_bid}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    sel_res = json.loads(res.read().decode('utf-8'))
    assert sel_res['ok'] and sel_res['active_brand_id'] == new_bid, 'Brand select failed'
    print(f'[LIVE TEST 9b] Brand selected OK: {new_bid}')

    # 10. Restore Original Brand & Clean Up
    req = urllib.request.Request(f'{base}/api/brands/select', data=json.dumps({'brand_id': orig_bid}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    urllib.request.urlopen(req)

    req = urllib.request.Request(f'{base}/api/brands/delete', data=json.dumps({'brand_id': new_bid}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req)
    del_res = json.loads(res.read().decode('utf-8'))
    assert del_res['ok'], 'Brand delete failed'
    print(f'[LIVE TEST 10] Brand cleaned up OK: {new_bid}')

    # 11. Media Scan & Random Pair Endpoints
    loan_path = str(BASE_DIR / 'loan')
    enc_path = urllib.parse.quote(loan_path)
    res = urllib.request.urlopen(f'{base}/api/media/scan?folder={enc_path}')
    media_scan = json.loads(res.read().decode('utf-8'))
    assert media_scan['ok'] and media_scan['total_videos'] == 7 and media_scan['paired_count'] == 7, 'Media scan failed'
    print(f'[LIVE TEST 11a] Media scan OK: {media_scan["total_videos"]} videos, {media_scan["paired_count"]} paired text captions.')

    res = urllib.request.urlopen(f'{base}/api/brand/brand_loan/media-pairs')
    pairs_data = json.loads(res.read().decode('utf-8'))
    assert pairs_data['ok'] and pairs_data['total_videos'] == 7, 'Brand media pairs failed'
    print(f'[LIVE TEST 11b] Brand media pairs endpoint OK: {pairs_data["total_videos"]} videos discovered.')

    res = urllib.request.urlopen(f'{base}/api/brand/brand_loan/random-pair')
    rand_data = json.loads(res.read().decode('utf-8'))
    assert rand_data['ok'] and rand_data['pair']['has_text'] and len(rand_data['pair']['caption']) > 100, 'Random pair failed'
    print(f'[LIVE TEST 11c] Brand random pair OK: selected {rand_data["pair"]["video_name"]} + {rand_data["pair"]["text_name"]}.')

    # 12. Input Restriction Endpoints
    res = urllib.request.urlopen(f'{base}/api/input-restriction/status')
    st_data = json.loads(res.read().decode('utf-8'))
    assert st_data['ok'] and not st_data['restricted'], 'Initial restriction status mismatch'
    print('[LIVE TEST 12a] Input restriction status endpoint OK: UNRESTRICTED.')

    req = urllib.request.Request(
        f'{base}/api/input-restriction/block',
        data=json.dumps({'reason': 'Live API Verification', 'timeout': 5.0}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    res = urllib.request.urlopen(req)
    blk_data = json.loads(res.read().decode('utf-8'))
    assert blk_data['ok'] and blk_data['status']['restricted'], 'Input block failed'
    print('[LIVE TEST 12b] Input restriction block endpoint OK: LOCKED.')

    req = urllib.request.Request(
        f'{base}/api/input-restriction/release',
        data=b'{}',
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    res = urllib.request.urlopen(req)
    rel_data = json.loads(res.read().decode('utf-8'))
    assert rel_data['ok'] and not rel_data['status']['restricted'], 'Input release failed'
    print('[LIVE TEST 12c] Input restriction release endpoint OK: RELEASED.')

    # 13. Safety Limit & Enriched Pages Endpoints
    limit_payload = {'max_publications_per_day': 7}
    req = urllib.request.Request(
        f'{base}/api/safety-limit',
        data=json.dumps(limit_payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    res = urllib.request.urlopen(req)
    limit_res = json.loads(res.read().decode('utf-8'))
    assert limit_res['ok'] and limit_res['max_publications_per_day'] == 7, 'Safety limit failed'
    print('[LIVE TEST 13a] Safety limit endpoint OK: 7 reels/day per page.')

    res = urllib.request.urlopen(f'{base}/api/pages')
    pages_res = json.loads(res.read().decode('utf-8'))
    assert pages_res['ok'] and len(pages_res['pages']) > 0, 'Enriched pages endpoint failed'
    first_p = pages_res['pages'][0]
    assert 'today_published_count' in first_p and 'max_publications_per_day' in first_p, 'Page missing enriched safety fields'
    print(f'[LIVE TEST 13b] Enriched pages endpoint OK: {first_p["name"]} ({first_p["today_published_count"]}/{first_p["max_publications_per_day"]} published today).')
    
    print('='*70)
    print('ALL LIVE API TESTS PASSED SUCCESSFULLY! (100% OPERATIONAL)')
    print('='*70)

if __name__ == '__main__':
    test_api()
