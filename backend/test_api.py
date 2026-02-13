"""
API動作確認テストスクリプト
バックエンドAPIが正しく動作しているかを確認
"""
import requests
import json
import sys


API_BASE_URL = "http://localhost:8000"


def test_health_check():
    """ヘルスチェック"""
    print("=== ヘルスチェック ===")
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        print(f"ステータスコード: {response.status_code}")
        print(f"レスポンス: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200
    except Exception as e:
        print(f"エラー: {e}")
        return False


def test_get_elevation(lat=35.6762, lon=139.6503):
    """標高取得テスト"""
    print(f"\n=== 標高取得テスト ===")
    print(f"座標: ({lat}, {lon})")
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/elevation",
            params={"lat": lat, "lon": lon}
        )
        print(f"ステータスコード: {response.status_code}")
        print(f"レスポンス: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200
    except Exception as e:
        print(f"エラー: {e}")
        return False


def test_find_evacuation(lat=35.6762, lon=139.6503):
    """避難先検索テスト"""
    print(f"\n=== 避難先検索テスト ===")
    print(f"現在地: ({lat}, {lon})")
    
    payload = {
        "lat": lat,
        "lon": lon,
        "transport_mode": "walking",
        "max_distance": 2000.0,
        "min_elevation_gain": 10.0
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/evacuation",
            json=payload
        )
        print(f"ステータスコード: {response.status_code}")
        
        data = response.json()
        print(f"\n現在地標高: {data.get('current_location', {}).get('elevation', 'N/A')} m")
        
        destinations = data.get('destinations', [])
        print(f"避難先候補数: {len(destinations)}")
        
        if destinations:
            print("\n--- 上位3件 ---")
            for i, dest in enumerate(destinations[:3], 1):
                print(f"{i}. 標高: {dest['elevation']:.1f}m "
                      f"(+{dest['elevation_gain']:.1f}m), "
                      f"距離: {dest['distance']:.0f}m, "
                      f"スコア: {dest['safety_score']:.1f}")
        
        return response.status_code == 200
    except Exception as e:
        print(f"エラー: {e}")
        return False


def test_elevation_profile(
    start_lat=35.6762, start_lon=139.6503,
    end_lat=35.6800, end_lon=139.6550
):
    """標高プロファイルテスト"""
    print(f"\n=== 標高プロファイルテスト ===")
    print(f"始点: ({start_lat}, {start_lon})")
    print(f"終点: ({end_lat}, {end_lon})")
    
    payload = {
        "start_lat": start_lat,
        "start_lon": start_lon,
        "end_lat": end_lat,
        "end_lon": end_lon,
        "num_points": 20
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/elevation-profile",
            json=payload
        )
        print(f"ステータスコード: {response.status_code}")
        
        data = response.json()
        print(f"総距離: {data.get('total_distance', 'N/A')} m")
        print(f"標高差: {data.get('elevation_gain', 'N/A')} m")
        
        profile = data.get('profile', [])
        if profile:
            print(f"\nサンプルポイント数: {len(profile)}")
            print("最初の3ポイント:")
            for p in profile[:3]:
                print(f"  距離 {p['distance']:.0f}m: 標高 {p['elevation']:.1f}m")
        
        return response.status_code == 200
    except Exception as e:
        print(f"エラー: {e}")
        return False


def main():
    """メイン処理"""
    print("=" * 50)
    print("避難ナビゲーションAPI テストスクリプト")
    print("=" * 50)
    
    # テストを実行
    results = []
    
    results.append(("ヘルスチェック", test_health_check()))
    results.append(("標高取得", test_get_elevation()))
    results.append(("避難先検索", test_find_evacuation()))
    results.append(("標高プロファイル", test_elevation_profile()))
    
    # 結果をまとめて表示
    print("\n" + "=" * 50)
    print("テスト結果サマリー")
    print("=" * 50)
    
    for test_name, result in results:
        status = "✓ 成功" if result else "✗ 失敗"
        print(f"{test_name}: {status}")
    
    # 全て成功したか確認
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 50)
    if all_passed:
        print("全てのテストが成功しました！")
        return 0
    else:
        print("一部のテストが失敗しました。")
        print("バックエンドが起動しているか、標高データが正しく読み込まれているか確認してください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
