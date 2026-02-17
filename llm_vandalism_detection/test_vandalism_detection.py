#!/usr/bin/env python3
"""
Unit tests for vandalism detection using the real LLM API.
Tests known vandalism cases from electrum-locale repository.

Run with environment variables, e.g.:
OPENAI_BASE_URL=https://api.ppq.ai OPENAI_MODEL=google/gemini-3-flash-preview OPENAI_API_KEY=ABC
"""

import asyncio
import os
import sys
import unittest

import aiohttp

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_vandalism_detection import classify_translation_async, get_concurrency


class AsyncVandalismTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class that provides a shared aiohttp session and semaphore."""

    _session: aiohttp.ClientSession = None
    _semaphore: asyncio.Semaphore = None

    async def asyncSetUp(self):
        self._session = aiohttp.ClientSession()
        self._semaphore = asyncio.Semaphore(get_concurrency())

    async def asyncTearDown(self):
        await self._session.close()

    async def classify(self, msgid: str, msgstr: str, lang: str) -> str:
        return await classify_translation_async(
            self._session, self._semaphore, msgid, msgstr, lang
        )


class TestVandalismDetection(AsyncVandalismTestCase):
    """
    Tests that known vandalism cases are correctly classified as Spam.
    These are real examples from the electrum-locale repository.
    """

    async def test_fr_FR_redo_thongchai(self):
        """fr_FR: '&Redo' translated as 'Thongchai' (unrelated name)"""
        result = await self.classify("&Redo", "Thongchai", "fr_FR")
        self.assertEqual(result, "Spam", "Unrelated name substitution should be Spam")

    async def test_fr_FR_cancellation_txid(self):
        """fr_FR: 'Cancellation Transaction ID' translated as actual txid hash"""
        result = await self.classify(
            "Cancellation Transaction ID",
            "edbd3224d120d8304d2194287c4b267707b50b2be46a78409d701327d9d47476\n",
            "fr_FR"
        )
        self.assertEqual(result, "Spam", "Injected transaction hash should be Spam")

    async def test_fa_IR_script_shah2026(self):
        """fa_IR: '- an arbitrary on-chain script, e.g.:' translated as 'shah2026'"""
        result = await self.classify(
            "- an arbitrary on-chain script, e.g.:",
            "shah2026",
            "fa_IR"
        )
        self.assertEqual(result, "Spam", "Username/handle substitution should be Spam")

    async def test_ro_RO_bitcoin_address_romana(self):
        """ro_RO: '- a Bitcoin address or BIP21 URI' translated as 'Română română'"""
        result = await self.classify(
            "- a Bitcoin address or BIP21 URI",
            "Română română ",
            "ro_RO"
        )
        self.assertEqual(result, "Spam", "Meaningless language name substitution should be Spam")

    async def test_vi_VN_amount_number(self):
        """vi_VN: 'Amount to be sent' translated as '10000000000' (8 years old)"""
        result = await self.classify(
            "Amount to be sent",
            "10000000000",
            "vi_VN"
        )
        self.assertEqual(result, "Spam", "Random number substitution should be Spam")

    async def test_cs_CZ_paper_email(self):
        """cs_CZ: Instructions translated as email address (2 years old)"""
        result = await self.classify(
            "1. Place this paper on a flat and well illuminated surface.",
            "veronikatilke33@seznam.cz",
            "cs_CZ"
        )
        self.assertEqual(result, "Spam", "Email address injection should be Spam")

    async def test_es_ES_amount_received_email(self):
        """es_ES: 'Amount received: {}' translated as email address"""
        result = await self.classify(
            "Amount received: {}",
            "cmc6686@gmail.com",
            "es_ES"
        )
        self.assertEqual(result, "Spam", "Email address injection should be Spam")

    async def test_fa_IR_undo_username(self):
        """fa_IR: '&Undo' translated as 'Rastakh8888'"""
        result = await self.classify(
            "&Undo",
            "Rastakh8888\n",
            "fa_IR"
        )
        self.assertEqual(result, "Spam", "Username substitution should be Spam")

    async def test_fr_FR_avoid_spending_btc_address(self):
        """fr_FR: Address usage warning translated as BTC address (stealing-oriented)"""
        result = await self.classify(
            "Avoid spending from used addresses",
            "bc1qgdl5a90ccznwteha436fn52nekdwuu9ld32n3c",
            "fr_FR"
        )
        self.assertEqual(result, "Spam", "Bitcoin address injection should be Spam")

    async def test_ar_SA_alert_address_btc_address(self):
        """ar_SA: 'Alert Address' translated as BTC address (stealing-oriented)"""
        result = await self.classify(
            "Alert Address",
            "bc1q393et0s9tv82udvjqfrupyv90s3fqvcfglhrea",
            "ar_SA"
        )
        self.assertEqual(result, "Spam", "Bitcoin address injection should be Spam")


class TestVandalismURL(AsyncVandalismTestCase):
    """Tests for URL injection vandalism."""

    async def test_url_injection_random(self):
        """URL injected into unrelated translation"""
        result = await self.classify(
            "Wallet settings",
            "https://freebitcoin.com/claim-now",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "Random URL injection should be Spam")

    async def test_url_injection_electrum_update(self):
        """URL injected into unrelated translation"""
        result = await self.classify(
            "Download the update from the Electrum website.",
            "Lade die Electrum Aktualisierung von electrum.io herunter.",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "Electrum update URL injection should be Spam")

    async def test_telegram_link_injection(self):
        """Telegram link injected"""
        result = await self.classify(
            "Please wait...",
            "t.me/cryptotrader_group",
            "ru_RU"
        )
        self.assertEqual(result, "Spam", "Telegram link injection should be Spam")

    async def test_phone_number_injection(self):
        """Phone number injected instead of translation"""
        result = await self.classify(
            "Network status",
            "+1-800-555-0199",
            "es_ES"
        )
        self.assertEqual(result, "Spam", "Phone number injection should be Spam")


class TestVandalismPoliticalAdvertising(AsyncVandalismTestCase):
    """Tests for political/advertising vandalism."""

    async def test_advertising_injection(self):
        """Advertising text injected"""
        result = await self.classify(
            "Confirm transaction",
            "Buy cheap electronics at bestdeals.com!",
            "it_IT"
        )
        self.assertEqual(result, "Spam", "Advertising injection should be Spam")

    async def test_political_slogan(self):
        """Political slogan injected"""
        result = await self.classify(
            "Balance",
            "Vote for candidate XYZ 2026",
            "pt_BR"
        )
        self.assertEqual(result, "Spam", "Political slogan injection should be Spam")


class TestVandalismGibberish(AsyncVandalismTestCase):
    """Tests for gibberish/random content."""

    async def test_random_characters(self):
        """Random character sequence"""
        result = await self.classify(
            "Transaction fee",
            "asdfghjkl qwerty zxcvbnm",
            "nl_NL"
        )
        self.assertEqual(result, "Spam", "Random characters should be Spam")

    async def test_keyboard_mash(self):
        """Keyboard mashing"""
        result = await self.classify(
            "Enter password",
            "jjjjjjjjjjjjjjjjjjjj",
            "pl_PL"
        )
        self.assertEqual(result, "Spam", "Keyboard mash should be Spam")

    async def test_emoji_spam(self):
        """Emoji spam instead of translation"""
        result = await self.classify(
            "Send Bitcoin",
            "\U0001f680\U0001f680\U0001f680\U0001f4b0\U0001f4b0\U0001f4b0\U0001f525\U0001f525\U0001f525",
            "ko_KR"
        )
        self.assertEqual(result, "Spam", "Emoji spam should be Spam")


class TestVandalismCryptoAddresses(AsyncVandalismTestCase):
    """Tests for cryptocurrency address injection."""

    async def test_ethereum_address_injection(self):
        """Ethereum address injected"""
        result = await self.classify(
            "Receive",
            "0x742d35Cc6634C0532925a3b844Bc9e7595f8eA12",
            "zh_CN"
        )
        self.assertEqual(result, "Spam", "Ethereum address injection should be Spam")

    async def test_litecoin_address_injection(self):
        """Litecoin address injected"""
        result = await self.classify(
            "Copy address",
            "LTC1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
            "tr_TR"
        )
        self.assertEqual(result, "Spam", "Litecoin address injection should be Spam")

    async def test_monero_address_injection(self):
        """Monero address injected"""
        result = await self.classify(
            "Wallet backup",
            "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A",
            "sv_SE"
        )
        self.assertEqual(result, "Spam", "Monero address injection should be Spam")


class TestVandalismSocialMedia(AsyncVandalismTestCase):
    """Tests for social media handle injection."""

    async def test_twitter_handle_injection(self):
        """Twitter/X handle injected"""
        result = await self.classify(
            "Help",
            "@follow_me_for_free_btc",
            "hu_HU"
        )
        self.assertEqual(result, "Spam", "Twitter handle injection should be Spam")

    async def test_discord_injection(self):
        """Discord server link injected"""
        result = await self.classify(
            "About",
            "discord.gg/freecrypto",
            "cs_CZ"
        )
        self.assertEqual(result, "Spam", "Discord link injection should be Spam")


class TestVandalismWrongLanguage(AsyncVandalismTestCase):
    """Tests for completely wrong target language."""

    async def test_wrong_script_cyrillic_for_japanese(self):
        """Cyrillic text for Japanese target"""
        result = await self.classify(
            "Settings",
            "Привет мир",
            "ja_JP"
        )
        self.assertEqual(result, "Spam", "Cyrillic for Japanese target should be Spam")

    async def test_wrong_script_arabic_for_german(self):
        """Arabic text for German target"""
        result = await self.classify(
            "Confirm",
            "مرحبا بالعالم",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "Arabic for German target should be Spam")


class TestGenuineTranslations(AsyncVandalismTestCase):
    """
    Control tests to ensure legitimate translations are not flagged.
    """

    async def test_genuine_fr_FR(self):
        """French translation should be Genuine"""
        result = await self.classify(
            "Amount to be sent",
            "Montant à envoyer",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Valid French translation should be Genuine")

    async def test_genuine_de_DE(self):
        """German translation should be Genuine"""
        result = await self.classify(
            "Bitcoin Address",
            "Bitcoin-Adresse",
            "de_DE"
        )
        self.assertEqual(result, "Genuine", "Valid German translation should be Genuine")

    async def test_genuine_ja_JP(self):
        """Japanese translation should be Genuine"""
        result = await self.classify(
            "Send",
            "送金",
            "ja_JP"
        )
        self.assertEqual(result, "Genuine", "Valid Japanese translation should be Genuine")

    async def test_genuine_technical_terms_preserved(self):
        """Technical terms left untranslated should be Genuine"""
        result = await self.classify(
            "BIP21 URI",
            "URI BIP21",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Technical terms preservation should be Genuine")

    async def test_genuine_zh_CN(self):
        """Chinese simplified translation should be Genuine"""
        result = await self.classify(
            "Wallet",
            "钱包",
            "zh_CN"
        )
        self.assertEqual(result, "Genuine", "Valid Chinese translation should be Genuine")

    async def test_genuine_ar_SA(self):
        """Arabic translation should be Genuine"""
        result = await self.classify(
            "Password",
            "كلمة المرور",
            "ar_SA"
        )
        self.assertEqual(result, "Genuine", "Valid Arabic translation should be Genuine")

    async def test_genuine_ru_RU(self):
        """Russian translation should be Genuine"""
        result = await self.classify(
            "Transaction",
            "Транзакция",
            "ru_RU"
        )
        self.assertEqual(result, "Genuine", "Valid Russian translation should be Genuine")

    async def test_genuine_ko_KR(self):
        """Korean translation should be Genuine"""
        result = await self.classify(
            "Confirm",
            "확인",
            "ko_KR"
        )
        self.assertEqual(result, "Genuine", "Valid Korean translation should be Genuine")

    async def test_genuine_pt_BR(self):
        """Portuguese (Brazil) translation should be Genuine"""
        result = await self.classify(
            "Receive",
            "Receber",
            "pt_BR"
        )
        self.assertEqual(result, "Genuine", "Valid Portuguese translation should be Genuine")

    async def test_genuine_placeholder_preserved(self):
        """Placeholders correctly preserved"""
        result = await self.classify(
            "Amount received: {}",
            "Montant reçu : {}",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Placeholder preservation should be Genuine")

    async def test_genuine_qt_markup_preserved(self):
        """Qt markup preserved in translation"""
        result = await self.classify(
            "&File",
            "&Fichier",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Qt markup preservation should be Genuine")

    async def test_genuine_html_markup(self):
        """HTML markup in translation"""
        result = await self.classify(
            "<b>Warning:</b> This action cannot be undone",
            "<b>Avertissement :</b> Cette action ne peut pas être annulée",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "HTML markup translation should be Genuine")

    async def test_genuine_technical_domain_terms(self):
        """Domain-specific technical terms"""
        result = await self.classify(
            "CPFP transaction",
            "Transaction CPFP",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Technical domain terms should be Genuine")

    async def test_genuine_bitcoin_terminology(self):
        """Bitcoin-specific terminology preserved"""
        result = await self.classify(
            "Satoshis per byte",
            "Satoshis par octet",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Bitcoin terminology should be Genuine")

    async def test_genuine_long_instruction_text(self):
        """Longer instructional text"""
        result = await self.classify(
            "A CPFP is a transaction that sends an unconfirmed output back to yourself, with a high fee.",
            "Un CPFP est une transaction qui vous renvoie une sortie non confirmée, avec des frais élevés.",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Long translated text should be Genuine")

    async def test_genuine_idiomatic_translation(self):
        """Idiomatic translation that differs from literal"""
        result = await self.classify(
            "Got it",
            "D'accord",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Idiomatic translations should be Genuine")


class TestEdgeCases(AsyncVandalismTestCase):
    """Tests for edge cases and boundary conditions."""

    async def test_partial_translation_genuine(self):
        """Partial translation should still be Genuine"""
        result = await self.classify(
            "Bitcoin wallet backup",
            "Bitcoin wallet サックアップ",
            "ja_JP"
        )
        self.assertEqual(result, "Genuine", "Partial translation should be Genuine")

    async def test_abbreviation_preserved(self):
        """Common abbreviation preserved"""
        result = await self.classify(
            "BTC",
            "BTC",
            "es_ES"
        )
        self.assertEqual(result, "Genuine", "Preserved abbreviation should be Genuine")

    async def test_number_format_different(self):
        """Number formatting can vary by locale"""
        result = await self.classify(
            "1,000.00 BTC",
            "1.000,00 BTC",
            "de_DE"
        )
        self.assertEqual(result, "Genuine", "Locale-specific number format should be Genuine")


class TestVandalismSeedPhraseInjection(AsyncVandalismTestCase):
    """Tests for seed phrase / private key injection attempts."""

    async def test_seed_phrase_injection(self):
        """Seed phrase words injected as translation"""
        result = await self.classify(
            "Enter your password",
            "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "Seed phrase injection should be Spam")

    async def test_private_key_wif_injection(self):
        """WIF private key injected"""
        result = await self.classify(
            "Backup wallet",
            "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ",
            "fr_FR"
        )
        self.assertEqual(result, "Spam", "Private key injection should be Spam")

    async def test_hex_private_key_injection(self):
        """Hex private key injected"""
        result = await self.classify(
            "Sign message",
            "e8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35",
            "it_IT"
        )
        self.assertEqual(result, "Spam", "Hex key injection should be Spam")


class TestVandalismOffensiveContent(AsyncVandalismTestCase):
    """Tests for offensive / inappropriate content."""

    async def test_profanity_injection(self):
        """Profanity injected instead of translation"""
        result = await self.classify(
            "Loading wallet...",
            "Fuck this stupid app",
            "en_GB"
        )
        self.assertEqual(result, "Spam", "Profanity injection should be Spam")

    async def test_insult_injection(self):
        """Personal insult injected"""
        result = await self.classify(
            "Transaction complete",
            "You are an idiot for using this",
            "es_ES"
        )
        self.assertEqual(result, "Spam", "Insult injection should be Spam")


class TestVandalismPromotionalContent(AsyncVandalismTestCase):
    """Tests for promotional / marketing spam."""

    async def test_casino_promotion(self):
        """Online casino promotion injected"""
        result = await self.classify(
            "Fee estimation",
            "Win big at CryptoSlots Casino! Deposit now!",
            "pt_BR"
        )
        self.assertEqual(result, "Spam", "Casino promotion should be Spam")

    async def test_investment_scam(self):
        """Investment scam text injected"""
        result = await self.classify(
            "Verify signature",
            "Double your Bitcoin in 24 hours! Send to this address!",
            "ru_RU"
        )
        self.assertEqual(result, "Spam", "Investment scam should be Spam")

    async def test_job_offer_spam(self):
        """Fake job offer spam"""
        result = await self.classify(
            "Address type",
            "Work from home $5000/week contact john@gmail.com",
            "nl_NL"
        )
        self.assertEqual(result, "Spam", "Job offer spam should be Spam")


class TestVandalismIdentityInjection(AsyncVandalismTestCase):
    """Tests for personal identity / name injection."""

    async def test_random_person_name(self):
        """Random person name injected"""
        result = await self.classify(
            "&Copy",
            "John Smith",
            "zh_CN"
        )
        self.assertEqual(result, "Spam", "Random name injection should be Spam")

    async def test_company_name_injection(self):
        """Unrelated company name injected"""
        result = await self.classify(
            "Block height",
            "Microsoft Corporation",
            "ja_JP"
        )
        self.assertEqual(result, "Spam", "Company name injection should be Spam")

    async def test_gamer_tag_injection(self):
        """Gaming handle / gamer tag injected"""
        result = await self.classify(
            "Sweep all",
            "xXx_Pr0Gamer_420_xXx",
            "ko_KR"
        )
        self.assertEqual(result, "Spam", "Gamer tag injection should be Spam")


class TestVandalismDateTimeInjection(AsyncVandalismTestCase):
    """Tests for arbitrary date/time injection."""

    async def test_random_date_injection(self):
        """Random date injected"""
        result = await self.classify(
            "Confirm payment",
            "2025-03-15 14:32:00",
            "sv_SE"
        )
        self.assertEqual(result, "Spam", "Random date injection should be Spam")

    async def test_countdown_injection(self):
        """Countdown text injected"""
        result = await self.classify(
            "Sign transaction",
            "Only 3 days left until the big event!",
            "da_DK"
        )
        self.assertEqual(result, "Spam", "Countdown injection should be Spam")


class TestVandalismCodeInjection(AsyncVandalismTestCase):
    """Tests for code/script injection attempts."""

    async def test_javascript_injection(self):
        """JavaScript code injected"""
        result = await self.classify(
            "Click to continue",
            "<script>alert('Klicken um fortzufahren')</script>",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "JavaScript injection should be Spam")

    async def test_qt_markup_injection(self):
        """Qt markup injected"""
        result = await self.classify(
            "Click to continue",
            "<a href='https://electrum.io/landing'>Klicken um fortzufahren</a>",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "Qt markup injection should be Spam")

    async def test_sql_injection_attempt(self):
        """SQL injection attempt"""
        result = await self.classify(
            "Search",
            "'; DROP TABLE wallets; --",
            "pl_PL"
        )
        self.assertEqual(result, "Spam", "SQL injection should be Spam")


class TestGenuineComplexTranslations(AsyncVandalismTestCase):
    """Tests for complex genuine translations that might be edge cases."""

    async def test_genuine_with_numbers(self):
        """Translation containing legitimate numbers"""
        result = await self.classify(
            "Requires 2 confirmations",
            "Requiert 2 confirmations",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Translation with numbers should be Genuine")

    async def test_genuine_plural_form(self):
        """Plural form translation"""
        result = await self.classify(
            "{} confirmations",
            "{} confirmations",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Plural form should be Genuine")

    async def test_genuine_empty_placeholder(self):
        """String that is just a placeholder"""
        result = await self.classify(
            "%s",
            "%s",
            "de_DE"
        )
        self.assertEqual(result, "Genuine", "Placeholder-only string should be Genuine")

    async def test_genuine_mixed_scripts_thai(self):
        """Thai translation with English technical terms"""
        result = await self.classify(
            "Bitcoin wallet",
            "กระเป๋า Bitcoin",
            "th_TH"
        )
        self.assertEqual(result, "Genuine", "Thai translation should be Genuine")

    async def test_genuine_mixed_scripts_hebrew(self):
        """Hebrew translation with mixed direction"""
        result = await self.classify(
            "Send BTC",
            "שלח BTC",
            "he_IL"
        )
        self.assertEqual(result, "Genuine", "Hebrew translation should be Genuine")

    async def test_genuine_mixed_scripts_hindi(self):
        """Hindi translation"""
        result = await self.classify(
            "Wallet",
            "वॉलेट",
            "hi_IN"
        )
        self.assertEqual(result, "Genuine", "Hindi translation should be Genuine")

    async def test_genuine_transliteration(self):
        """Transliteration is acceptable"""
        result = await self.classify(
            "Bitcoin",
            "比特币",
            "zh_CN"
        )
        self.assertEqual(result, "Genuine", "Transliteration should be Genuine")

    async def test_genuine_complex_qt_markup(self):
        """Complex Qt markup with multiple elements"""
        result = await self.classify(
            "&Edit | &Delete | &Copy",
            "&Éditer | &Supprimer | &Copier",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Complex Qt markup should be Genuine")

    async def test_genuine_multiple_placeholders(self):
        """Multiple placeholders in string"""
        result = await self.classify(
            "Sent {amount} to {address}",
            "Envoyé {amount} à {address}",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Multiple placeholders should be Genuine")

    async def test_genuine_error_message(self):
        """Error message translation"""
        result = await self.classify(
            "Error: Insufficient funds",
            "Erreur : Fonds insuffisants",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Error message translation should be Genuine")

    async def test_genuine_question_text(self):
        """Question text translation"""
        result = await self.classify(
            "Are you sure you want to delete this wallet?",
            "Êtes-vous sûr de vouloir supprimer ce portefeuille ?",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Question translation should be Genuine")

    async def test_genuine_url_in_original(self):
        """URL present in original should be preserved"""
        result = await self.classify(
            "Visit https://electrum.org for more information",
            "Visitez https://electrum.org pour plus d'informations",
            "fr_FR"
        )
        self.assertEqual(result, "Genuine", "Preserved URL should be Genuine")


class TestVandalismMoreCryptoScams(AsyncVandalismTestCase):
    """Additional tests for crypto-specific scams."""

    async def test_fake_support_message(self):
        """Fake support message injection"""
        result = await self.classify(
            "Help",
            "For support contact admin@electrum-support.com",
            "de_DE"
        )
        self.assertEqual(result, "Spam", "Fake support message should be Spam")

    async def test_airdrop_scam(self):
        """Airdrop scam injection"""
        result = await self.classify(
            "Receive address",
            "Claim your free 1 BTC airdrop now!",
            "es_ES"
        )
        self.assertEqual(result, "Spam", "Airdrop scam should be Spam")

    async def test_exchange_promotion(self):
        """Exchange promotion injection"""
        result = await self.classify(
            "Exchange rate",
            "Trade on BinanceScam exchange with 0% fees!",
            "zh_TW"
        )
        self.assertEqual(result, "Spam", "Exchange promotion should be Spam")


class TestVandalismSpecialCharacters(AsyncVandalismTestCase):
    """Tests for special character abuse."""

    async def test_zalgo_text(self):
        """Zalgo/corrupted text injection"""
        result = await self.classify(
            "Balance",
            "B̷̢̺̈́ą̸̛l̷̰͑a̸̱͝n̵̗̏c̸̣̊e̷̤̔",
            "en_US"
        )
        self.assertEqual(result, "Spam", "Zalgo text should be Spam")

    async def test_invisible_characters(self):
        """Zero-width characters abuse"""
        result = await self.classify(
            "Send",
            "S\u200be\u200bn\u200bd\u200b\u200b\u200bClick here for free BTC",
            "fr_FR"
        )
        self.assertEqual(result, "Spam", "Hidden text injection should be Spam")

    async def test_excessive_punctuation(self):
        """Excessive punctuation spam"""
        result = await self.classify(
            "Warning!",
            "!!!!!!!!!!!!!!!!!!!!",
            "it_IT"
        )
        self.assertEqual(result, "Spam", "Excessive punctuation should be Spam")


class TestVandalismIPAddresses(AsyncVandalismTestCase):
    """Tests for IP address injection."""

    async def test_ipv4_injection(self):
        """IPv4 address injected"""
        result = await self.classify(
            "Server settings",
            "192.168.1.100:8080",
            "ru_RU"
        )
        self.assertEqual(result, "Spam", "IPv4 injection should be Spam")

    async def test_ipv6_injection(self):
        """IPv6 address injected"""
        result = await self.classify(
            "Connect to node",
            "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            "ja_JP"
        )
        self.assertEqual(result, "Spam", "IPv6 injection should be Spam")


if __name__ == "__main__":
    unittest.main(verbosity=2)

