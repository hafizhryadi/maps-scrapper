import requests
import json
import time
from dotenv import load_dotenv
import os

# ----------------------------------------------------------------------
# KONFIGURASI
# ----------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv('API_KEY')
QUERY = "wisata di palemmbang"

# Anda bisa set hingga 60, karena itu batas maksimal dari API
MAX_RESULTS = 60 
# ----------------------------------------------------------------------


def get_paginated_google_maps_data(api_key, query, max_results):
    """
    Fungsi untuk mengambil data dari Google Maps API menggunakan pagination
    untuk mendapatkan lebih dari 20 hasil.
    """
    
    # URL untuk permintaan pertama (Text Search)
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {'query': query, 'key': api_key}

    collected_data = []

    # basic retry settings
    NETWORK_RETRIES = 3
    pagetoken_retry_attempts = 0

    while True:
        print(f"Mengirim permintaan ke Google Maps API... (Sudah terkumpul: {len(collected_data)} data)")

        # retry on network errors
        for attempt in range(1, NETWORK_RETRIES + 1):
            try:
                response = requests.get(base_url, params=params, timeout=10)
                try:
                    results = response.json()
                except ValueError:
                    print(f"Gagal mem-parsing JSON dari response (attempt {attempt}/{NETWORK_RETRIES}).")
                    results = {'status': 'INVALID_RESPONSE'}
                break
            except requests.RequestException as e:
                print(f"Permintaan gagal (attempt {attempt}/{NETWORK_RETRIES}): {e}")
                if attempt == NETWORK_RETRIES:
                    print("Gagal terhubung ke Google Maps API setelah beberapa percobaan. Menghentikan proses.")
                    return collected_data
                time.sleep(1 * attempt)

        status = results.get('status')
        if status != 'OK':
            # Handle some non-fatal statuses when using pagetoken
            if status == 'ZERO_RESULTS':
                print("Tidak ada hasil untuk query ini.")
                break
            if status == 'INVALID_REQUEST' and params.get('pagetoken'):
                # pagetoken sometimes needs a short delay to become valid
                pagetoken_retry_attempts += 1
                if pagetoken_retry_attempts > 5:
                    print("Token halaman berikutnya tidak valid setelah beberapa percobaan. Menghentikan pagination.")
                    break
                print("Token halaman berikutnya belum aktif, menunggu 2 detik dan mencoba lagi...")
                time.sleep(2)
                continue

            print(f"Error pada API: {status}")
            if 'error_message' in results:
                print(f"Pesan Error: {results['error_message']}")
            break

        # reset pagetoken retry counter when we have a good page
        pagetoken_retry_attempts = 0

        # Proses setiap tempat di halaman saat ini
        for place in results.get('results', []):
            # Cek apakah batas MAX_RESULTS sudah tercapai
            if len(collected_data) >= max_results:
                break

            # Ambil detail lengkap untuk setiap tempat (ini menggunakan credit API tambahan)
            place_id = place.get('place_id')
            if not place_id:
                continue

            details_url = "https://maps.googleapis.com/maps/api/place/details/json"
            fields_to_request = 'name,formatted_address,geometry,photos'
            details_params = {'place_id': place_id, 'fields': fields_to_request, 'key': api_key}

            # get details with retry
            details_results = None
            for attempt in range(1, NETWORK_RETRIES + 1):
                try:
                    details_response = requests.get(details_url, params=details_params, timeout=10)
                    try:
                        details_results = details_response.json()
                    except ValueError:
                        print(f"Gagal mem-parsing JSON detail untuk place_id {place_id} (attempt {attempt}/{NETWORK_RETRIES}).")
                        details_results = None
                    break
                except requests.RequestException as e:
                    print(f"Gagal mengambil detail (attempt {attempt}/{NETWORK_RETRIES}): {e}")
                    if attempt == NETWORK_RETRIES:
                        print(f"Lewati place_id {place_id} karena error berulang.")
                    time.sleep(1 * attempt)
            # small throttle between detail requests
            time.sleep(0.1)

            if not details_results or details_results.get('status') != 'OK':
                # skip this place if we couldn't get details
                continue

            result = details_results.get('result', {})

            nama = result.get('name', 'N/A')
            alamat = result.get('formatted_address', 'N/A')
            location = result.get('geometry', {}).get('location', {})
            latitude = location.get('lat')
            longitude = location.get('lng')

            # default values for images
            places_images = 'N/A'
            foto_url = 'N/A'
            if 'photos' in result and result['photos']:
                photo_reference = result['photos'][0].get('photo_reference')
                if photo_reference:
                    places_images = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference={photo_reference}&key={api_key}"
                    foto_url = places_images

            place_data = {
                'nama': nama,
                'alamat': alamat,
                'gps_coordinates': {
                    'lat': latitude,
                    'lng': longitude
                },
                'places_images': places_images
            }
            collected_data.append(place_data)

        # Cek apakah sudah mencapai batas atau tidak ada halaman berikutnya
        if len(collected_data) >= max_results or 'next_page_token' not in results:
            break

        # Siapkan untuk permintaan halaman berikutnya
        print("Ada halaman berikutnya, menunggu 2 detik sebelum mengambil...")
        time.sleep(2) # Jeda 2 detik adalah syarat dari Google agar token valid

        params = {'pagetoken': results['next_page_token'], 'key': api_key}

    return collected_data


# --- Jalankan Fungsi dan Cetak Hasil ---
if __name__ == "__main__":
    if not API_KEY:
        print("❌ KESALAHAN: API_KEY tidak ditemukan. Silakan set di environment atau di file .env sebagai API_KEY.")
    else:
        final_data = get_paginated_google_maps_data(API_KEY, QUERY, MAX_RESULTS)

        if final_data:
            print(f"\n✅ Proses Selesai. Berhasil mengumpulkan total {len(final_data)} data.")
            json_output = json.dumps(final_data, indent=4, ensure_ascii=False)

            with open('places_data.json', 'w', encoding='utf-8') as f:
                f.write(json_output)
            print("\nOutput 'places_data.json'")
        else:
            print("\nTidak ada data yang disimpan. Pastikan query Anda benar dan API Key memiliki akses yang memadai.")