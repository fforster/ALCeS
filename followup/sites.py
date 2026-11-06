"""Optical/IR observatory presets (region, name, latitude deg N, longitude deg E, height m).

Sources: the astropy observatory registry (EarthLocation.of_site, marked [a]) where available; otherwise published
site coordinates (approximate to ~0.01 deg, ample for night and airmass). Radio, neutrino and gravitational-wave
facilities of the registry are left out on purpose.
"""
SITES = [
    # --- Chile
    ("Chile", "Cerro Pachón (Rubin, SOAR, Gemini-S) [a]", -30.2446, -70.7494, 2663),
    ("Chile", "Cerro Tololo (CTIO) [a]", -30.1653, -70.8150, 2215),
    ("Chile", "La Silla (ESO) [a]", -29.2567, -70.7300, 2347),
    ("Chile", "Las Campanas (Magellan) [a]", -29.0033, -70.7017, 2282),
    ("Chile", "Cerro Paranal (VLT) [a]", -24.6274, -70.4050, 2669),
    ("Chile", "Cerro Armazones (ELT) [a]", -24.5987, -70.2013, 2817),
    ("Chile", "Ckoirama (Antofagasta) [a]", -24.0893, -69.9306, 965),
    # --- rest of South America
    ("South America", "CASLEO, El Leoncito (Argentina)", -31.7986, -69.2956, 2552),
    ("South America", "La Plata (Argentina) [a]", -34.9085, -57.9327, 16),
    ("South America", "Pico dos Dias, OPD (Brazil)", -22.5344, -45.5825, 1864),
    ("South America", "Llano del Hato, CIDA (Venezuela) [a]", 8.7900, -70.8667, 3610),
    # --- Mexico, USA, Canada, Caribbean
    ("North America", "San Pedro Mártir (Mexico) [a]", 31.0292, -115.4869, 2830),
    ("North America", "Guillermo Haro, Cananea (Mexico)", 31.0525, -110.3842, 2480),
    ("North America", "Kitt Peak (KPNO) [a]", 31.9633, -111.6000, 2120),
    ("North America", "Mt. Hopkins (FLWO, MMT) [a]", 31.6883, -110.8850, 2608),
    ("North America", "Catalina / Mt. Lemmon [a]", 32.4167, -110.7317, 2510),
    ("North America", "Mt. Graham (LBT) [a]", 32.7016, -109.8719, 2902),
    ("North America", "Apache Point (SDSS) [a]", 32.7800, -105.8200, 2798),
    ("North America", "McDonald (HET) [a]", 30.6814, -104.0147, 2026),
    ("North America", "Lowell, Happy Jack (LDT) [a]", 34.7443, -111.4225, 2337),
    ("North America", "Palomar (ZTF) [a]", 33.3560, -116.8630, 1706),
    ("North America", "Lick (Mt. Hamilton) [a]", 37.3433, -121.6367, 1290),
    ("North America", "Mont Mégantic (Canada) [a]", 45.4557, -71.1525, 1108),
    ("North America", "Dominion Astrophysical Obs. (Canada) [a]", 48.5217, -123.4167, 229),
    ("North America", "PEARL, Eureka (Nunavut, Canada)", 80.0530, -86.4160, 610),
    # --- Pacific
    ("Pacific", "Mauna Kea (Keck, Subaru, Gemini-N) [a]", 19.8283, -155.4783, 4160),
    ("Pacific", "Haleakalā (Maui) [a]", 20.7155, -156.1690, 3048),
    ("Pacific", "Mt. John (New Zealand) [a]", -43.9857, 170.4651, 1029),
    # --- Europe and Atlantic islands
    ("Europe", "Roque de los Muchachos (La Palma) [a]", 28.7583, -17.8800, 2327),
    ("Europe", "Teide (Tenerife) [a]", 28.3000, -16.5097, 2390),
    ("Europe", "Calar Alto (Spain) [a]", 37.2236, -2.5461, 2168),
    ("Europe", "Javalambre (Spain) [a]", 40.0420, -1.0161, 1956),
    ("Europe", "Pic du Midi (France)", 42.9364, 0.1425, 2877),
    ("Europe", "Haute-Provence (France) [a]", 43.9308, 5.7133, 650),
    ("Europe", "Asiago, Cima Ekar (Italy) [a]", 45.8486, 11.5811, 1413),
    ("Europe", "Wendelstein (Germany) [a]", 47.7036, 12.0121, 1838),
    ("Europe", "Ondřejov (Czechia)", 49.9106, 14.7808, 528),
    ("Europe", "Skinakas (Crete, Greece)", 35.2119, 24.8986, 1750),
    ("Europe", "Rozhen (Bulgaria)", 41.6930, 24.7392, 1759),
    ("Europe", "TÜBİTAK, Bakırlıtepe (Türkiye) [a]", 36.8242, 30.3356, 2500),
    # --- Middle East, Caucasus, Central Asia
    ("Middle East & Central Asia", "Wise (Israel) [a]", 30.5974, 34.7622, 875),
    ("Middle East & Central Asia", "Kottamia (Egypt)", 29.9314, 31.8292, 477),
    ("Middle East & Central Asia", "Iranian National Obs., Gargash (Iran)", 33.6740, 51.3180, 3600),
    ("Middle East & Central Asia", "SAO RAS, BTA (Russia)", 43.6467, 41.4406, 2070),
    ("Middle East & Central Asia", "Terskol (Russia)", 43.2744, 42.5008, 3143),
    ("Middle East & Central Asia", "Abastumani (Georgia)", 41.7542, 42.8197, 1650),
    ("Middle East & Central Asia", "Byurakan (Armenia)", 40.3306, 44.2742, 1405),
    ("Middle East & Central Asia", "Maidanak (Uzbekistan)", 38.6733, 66.8964, 2593),
    ("Middle East & Central Asia", "Assy-Turgen (Kazakhstan)", 43.2253, 77.8711, 2750),
    # --- South Asia
    ("South & East Asia", "Devasthal (DOT, India) [a]", 29.3610, 79.6844, 2424),
    ("South & East Asia", "Hanle (HCT, India) [a]", 32.7794, 78.9642, 4500),
    ("South & East Asia", "Mt. Abu (India)", 24.6536, 72.7794, 1680),
    ("South & East Asia", "Vainu Bappu, Kavalur (India) [a]", 12.5767, 78.8266, 725),
    # --- East and Southeast Asia
    ("South & East Asia", "Ali (Tibet, China)", 32.3264, 80.0266, 5100),
    ("South & East Asia", "Lenghu (Qinghai, China)", 38.6068, 93.8961, 4200),
    ("South & East Asia", "Lijiang (GMG, China) [a]", 26.6951, 100.0300, 3200),
    ("South & East Asia", "Xinglong (China) [a]", 40.3933, 117.5750, 950),
    ("South & East Asia", "Doi Inthanon (TNO, Thailand) [a]", 18.5906, 98.4867, 2457),
    ("South & East Asia", "Lulin (Taiwan)", 23.4686, 120.8736, 2862),
    ("South & East Asia", "Bohyunsan (Korea)", 36.1648, 128.9767, 1124),
    ("South & East Asia", "Okayama (Japan) [a]", 34.5771, 133.5940, 370),
    ("South & East Asia", "Kiso (Japan)", 35.7975, 137.6253, 1130),
    ("South & East Asia", "Bosscha, Lembang (Indonesia)", -6.8247, 107.6153, 1310),
    ("South & East Asia", "Timau National Obs. (Indonesia)", -9.5970, 123.9470, 1300),
    # --- Africa
    ("Africa", "SAAO Sutherland (SALT) [a]", -32.3758, 20.8108, 1798),
    ("Africa", "Oukaïmeden (Morocco)", 31.2061, -7.8664, 2750),
    ("Africa", "Entoto (Ethiopia)", 9.1000, 38.7600, 3200),
    ("Africa", "Gamsberg (Namibia)", -23.3400, 16.2300, 2347),
    # --- Australia
    ("Australia", "Siding Spring (AAT) [a]", -31.2734, 149.0612, 1149),
    ("Australia", "Mt. Stromlo (Canberra) [a]", -35.3207, 149.0243, 767),
    ("Australia", "Perth Observatory, Bickley", -32.0081, 116.1350, 391),
    # --- Antarctica
    ("Antarctica", "Dome C (Concordia)", -75.0999, 123.3326, 3233),
    ("Antarctica", "Dome A (Kunlun)", -80.3674, 77.3489, 4093),
    ("Antarctica", "South Pole (Amundsen-Scott)", -89.9900, -45.0000, 2835),
]
