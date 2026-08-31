/**
 * Słownik działów PKD 2007 (dwie pierwsze cyfry kodu).
 *
 * Świadomie na poziomie **działu**, a nie klasy. Klas jest ponad 650 i nie ma
 * ich w żadnym otwartym zbiorze danych, do którego udało się dotrzeć — a
 * wpisanie ich „z pamięci" oznaczałoby podawanie użytkownikowi opisów, których
 * poprawności nie da się zagwarantować. Dział pokrywa 100% kodów i jest
 * jednoznaczny, więc lepiej pokazać mniej, ale prawdziwie.
 *
 * Gdy pojawi się oficjalny słownik klas (GUS publikuje PKD jako HTML, nie jako
 * dane), wystarczy dołożyć drugą mapę i pokazywać dokładniejszy opis.
 */
export const PKD_SECTIONS: Record<string, string> = {
  "01": "Uprawy rolne, chów i hodowla zwierząt, łowiectwo",
  "02": "Leśnictwo i pozyskiwanie drewna",
  "03": "Rybactwo",
  "05": "Wydobywanie węgla kamiennego i brunatnego",
  "06": "Górnictwo ropy naftowej i gazu ziemnego",
  "07": "Górnictwo rud metali",
  "08": "Pozostałe górnictwo i wydobywanie",
  "09": "Działalność usługowa wspomagająca górnictwo",
  "10": "Produkcja artykułów spożywczych",
  "11": "Produkcja napojów",
  "12": "Produkcja wyrobów tytoniowych",
  "13": "Produkcja wyrobów tekstylnych",
  "14": "Produkcja odzieży",
  "15": "Produkcja skór i wyrobów ze skór",
  "16": "Produkcja wyrobów z drewna, korka, słomy i wikliny",
  "17": "Produkcja papieru i wyrobów z papieru",
  "18": "Poligrafia i reprodukcja zapisanych nośników",
  "19": "Wytwarzanie koksu i produktów rafinacji ropy naftowej",
  "20": "Produkcja chemikaliów i wyrobów chemicznych",
  "21": "Produkcja podstawowych substancji farmaceutycznych i leków",
  "22": "Produkcja wyrobów z gumy i tworzyw sztucznych",
  "23": "Produkcja wyrobów z pozostałych mineralnych surowców niemetalicznych",
  "24": "Produkcja metali",
  "25": "Produkcja metalowych wyrobów gotowych",
  "26": "Produkcja komputerów, wyrobów elektronicznych i optycznych",
  "27": "Produkcja urządzeń elektrycznych",
  "28": "Produkcja maszyn i urządzeń",
  "29": "Produkcja pojazdów samochodowych i przyczep",
  "30": "Produkcja pozostałego sprzętu transportowego",
  "31": "Produkcja mebli",
  "32": "Pozostała produkcja wyrobów",
  "33": "Naprawa, konserwacja i instalowanie maszyn i urządzeń",
  "35": "Wytwarzanie i zaopatrywanie w energię elektryczną, gaz, parę wodną",
  "36": "Pobór, uzdatnianie i dostarczanie wody",
  "37": "Odprowadzanie i oczyszczanie ścieków",
  "38": "Gospodarka odpadami, odzysk surowców",
  "39": "Rekultywacja i pozostałe usługi związane z gospodarką odpadami",
  "41": "Roboty budowlane związane ze wznoszeniem budynków",
  "42": "Roboty związane z budową obiektów inżynierii lądowej i wodnej",
  "43": "Roboty budowlane specjalistyczne",
  "45": "Handel hurtowy i detaliczny pojazdami samochodowymi, naprawa",
  "46": "Handel hurtowy, z wyłączeniem handlu pojazdami samochodowymi",
  "47": "Handel detaliczny, z wyłączeniem handlu pojazdami samochodowymi",
  "49": "Transport lądowy oraz transport rurociągowy",
  "50": "Transport wodny",
  "51": "Transport lotniczy",
  "52": "Magazynowanie i działalność usługowa wspomagająca transport",
  "53": "Działalność pocztowa i kurierska",
  "55": "Zakwaterowanie",
  "56": "Działalność usługowa związana z wyżywieniem",
  "58": "Działalność wydawnicza",
  "59": "Produkcja filmów, nagrań wideo, programów telewizyjnych i muzyki",
  "60": "Nadawanie programów ogólnodostępnych i abonamentowych",
  "61": "Telekomunikacja",
  "62": "Działalność związana z oprogramowaniem i doradztwem w zakresie informatyki",
  "63": "Działalność usługowa w zakresie informacji",
  "64": "Finansowa działalność usługowa, z wyłączeniem ubezpieczeń",
  "65": "Ubezpieczenia, reasekuracja i fundusze emerytalne",
  "66": "Działalność wspomagająca usługi finansowe i ubezpieczenia",
  "68": "Działalność związana z obsługą rynku nieruchomości",
  "69": "Działalność prawnicza, rachunkowo-księgowa i doradztwo podatkowe",
  "70": "Działalność firm centralnych; doradztwo związane z zarządzaniem",
  "71": "Działalność w zakresie architektury i inżynierii; badania i analizy",
  "72": "Badania naukowe i prace rozwojowe",
  "73": "Reklama, badanie rynku i opinii publicznej",
  "74": "Pozostała działalność profesjonalna, naukowa i techniczna",
  "75": "Działalność weterynaryjna",
  "77": "Wynajem i dzierżawa",
  "78": "Działalność związana z zatrudnieniem",
  "79": "Działalność organizatorów turystyki i pośredników turystycznych",
  "80": "Działalność detektywistyczna i ochroniarska",
  "81": "Działalność usługowa związana z utrzymaniem porządku w budynkach",
  "82": "Działalność związana z administracyjną obsługą biura",
  "84": "Administracja publiczna i obrona narodowa",
  "85": "Edukacja",
  "86": "Opieka zdrowotna",
  "87": "Pomoc społeczna z zakwaterowaniem",
  "88": "Pomoc społeczna bez zakwaterowania",
  "90": "Działalność twórcza związana z kulturą i rozrywką",
  "91": "Działalność bibliotek, archiwów, muzeów",
  "92": "Działalność związana z grami losowymi i zakładami wzajemnymi",
  "93": "Działalność sportowa, rozrywkowa i rekreacyjna",
  "94": "Działalność organizacji członkowskich",
  "95": "Naprawa i konserwacja komputerów oraz artykułów użytku osobistego",
  "96": "Pozostała indywidualna działalność usługowa",
  "97": "Gospodarstwa domowe zatrudniające pracowników",
  "99": "Organizacje i zespoły eksterytorialne",
};

/** Opis działu, do którego należy kod PKD. `null`, gdy kod jest nierozpoznany. */
export function describePkd(code: string): string | null {
  const digits = code.replace(/\D/g, "");
  if (digits.length < 2) return null;
  return PKD_SECTIONS[digits.slice(0, 2)] ?? null;
}

/** CEIDG skleja pozostałe kody separatorem `$##$`. */
export function splitPkdList(value: unknown): string[] {
  if (typeof value !== "string" || !value) return [];
  return value
    .split("$##$")
    .map((c) => c.trim())
    .filter(Boolean);
}
