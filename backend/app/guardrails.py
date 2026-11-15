"""Local intent agent: no model, provider call, or paid classifier is used.

This intentionally conservative policy recognises travel language and valid
trip-answer formats. Unknown requests get a clarification, never a model call.
It is a configurable vocabulary policy, not a claim of universal semantic or
multilingual abuse detection.
"""
import re
import unicodedata
from dataclasses import dataclass

from app.tourism import destination_route, directory


AGENT = 'Intent & Guardrail Agent'
TRAVEL_FALLBACK = ('I can help with travel planning in India, including destinations, itineraries, weather, '
                   'food, accommodation and transport. Please ask a travel-related question.')
PROFESSIONAL_REPLY = ('Please keep our conversation professional. Your message has been masked. '
                      'Please rephrase your travel question respectfully.')
CLARIFY_REPLY = ('I can help plan travel in India. Please share a destination or ask about your trip, '
                 'weather, attractions, meals, accommodation or transport.')

_ABUSE_WORDS = ('fuck', 'fucker', 'fucking', 'motherfucker', 'motherfucking', 'shit', 'shitty', 'bullshit',
                'bitch', 'bitches', 'asshole', 'arsehole', 'bastard', 'bastards', 'cunt', 'dickhead',
                'idiot', 'idiots', 'stupid', 'moron', 'wtf', 'chutiya', 'chutiye', 'madarchod', 'bhenchod', 'behenchod',
                'चूतिया', 'मादरचोद', 'बहनचोद')
_ABUSE = re.compile(r'(?<!\w)(?:' + '|'.join(sorted(_ABUSE_WORDS, key=len, reverse=True)) + r')(?!\w)', re.I)
_OBFUSCATED = re.compile(r'(?<!\w)(?:f[\W_]*[u*@][\W_]*c[\W_]*k(?:ing|er)?|'
                        r'sh[1!i]t|b[1!i]tch|a[s$][s$]h[o0]le|f[u*]ck|f\*{2,}k)(?!\w)', re.I)
_TRAVEL = re.compile(r'\b(?:travel(?:ling|ing|s)?|trips?|tour(?:s|ism|ist|ing)?|itinerar(?:y|ies)|'
    r'vacations?|holidays?|getaways?|honeymoon|weekend break|destinations?|sightseeing|attractions?|'
    r'visit(?:s|ing)?|explor(?:e|ing)|trek(?:s|king)?|hik(?:e|ing)|beach(?:es)?|temples?|museums?|'
    r'palaces?|forts?|parks?|waterfalls?|weather|forecasts?|rain(?:fall)?|temperatures?|'
    r'hotels?|hostels?|resorts?|homestays?|guest\s*houses?|accommodations?|lodging|overnight|'
    r'restaurants?|cafes?|cafés|breakfast|lunch|dinner|cuisine|vegetarian|vegan|'
    r'flights?|airports?|airlines?|trains?|railways?|buses?|bus|taxi|taxis|cab|cabs|'
    r'car rental|road\s*trip|transport|journey|boarding|departure|arrival|check[ -]?in|'
    r'tickets?|fares?|packing|suitcase|backpack|passport|visa|pilgrimage|wheelchair|'
    r'budget|sightseeing|day trip|local food|meal(?:s)?|stays?|route(?:s)?)\b', re.I)
_OFF_TOPIC = re.compile(r'\b(?:write|debug|explain|generate|fix|teach|solve|implement)\b.{0,45}'
    r'\b(?:code|python|javascript|java|sql|program|algorithm|equation|math|essay|poem|song|homework)\b|'
    r'\b(?:stock market|cryptocurrency|bitcoin|politics|elections?|president|prime minister|'
    r'programming|machine learning|neural networks?|homework|source code|system prompt|api keys?|ignore (?:all |previous )?instructions|'
    r'\b(?:train|build|create)\b.{0,30}\b(?:ai|language|prediction) model\b|'
    r'capital of|who won|cricket score|football score|medical diagnosis)\b', re.I)
_TRAVEL_PHRASE = re.compile(r'\b(?:where (?:can|should|could) (?:i|we) (?:go|eat|stay|explore)|'
    r'things to do|places to (?:see|go|eat|stay)|how (?:do i|can i|to) (?:get to|reach)|'
    r'take (?:me|us) somewhere|weekend getaway|get away for|somewhere (?:peaceful|quiet))\b', re.I)
_GREETINGS = {
    'hi': 'Hi!', 'hello': 'Hello!', 'hey': 'Hey!', 'hi there': 'Hi there!', 'hello there': 'Hello!',
    'good morning': 'Good morning!', 'good afternoon': 'Good afternoon!', 'good evening': 'Good evening!',
    'good night': 'Good night!', 'namaste': 'Namaste!', 'namaskar': 'Namaskar!', 'नमस्ते': 'नमस्ते!',
    'vanakkam': 'Vanakkam!', 'how are you': 'I’m ready to help!', 'how are you doing': 'I’m ready to help!',
    'thanks': 'You’re welcome!', 'thank you': 'You’re welcome!', 'thank you so much': 'You’re welcome!',
    'bye': 'Goodbye!', 'goodbye': 'Goodbye!', 'see you': 'See you!',
}
_CITIES = {v.casefold() for v in ('Pune', 'Mumbai', 'Bombay', 'Delhi', 'New Delhi', 'Bengaluru', 'Bangalore',
    'Chennai', 'Madras', 'Kolkata', 'Calcutta', 'Ahmedabad', 'Surat', 'Vadodara', 'Lucknow', 'Kanpur', 'Agra',
    'Varanasi', 'Rishikesh', 'Haridwar', 'Dehradun', 'Shimla', 'Manali', 'Amritsar', 'Chandigarh', 'Srinagar',
    'Leh', 'Jammu', 'Patna', 'Ranchi', 'Bhubaneswar', 'Puri', 'Guwahati', 'Shillong', 'Gangtok', 'Darjeeling',
    'Kochi', 'Coimbatore', 'Madurai', 'Ooty', 'Kodaikanal', 'Mangaluru', 'Mangalore', 'Udupi', 'Hampi',
    'Pondicherry', 'Puducherry', 'Nagpur', 'Nashik', 'Aurangabad', 'Indore', 'Bhopal', 'Gwalior', 'Jabalpur',
    'Raipur', 'Kozhikode', 'Kannur', 'Thiruvananthapuram', 'Trivandrum', 'Thrissur', 'Tirupati', 'Vijayawada')}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(text)) if unicodedata.category(c) != 'Cf')


def mask_text(text):
    clean = normalize(text)
    return _OBFUSCATED.sub('[masked]', _ABUSE.sub('[masked]', clean))


def sanitize(value):
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def has_abuse(value):
    if isinstance(value, str):
        text = normalize(value)
        return bool(_ABUSE.search(text) or _OBFUSCATED.search(text))
    if isinstance(value, dict):
        return any(has_abuse(v) for v in value.values())
    if isinstance(value, list):
        return any(has_abuse(v) for v in value)
    return False


@dataclass(frozen=True)
class Decision:
    intent: str
    allow_llm: bool
    message: str
    reply: str = ''

    def public(self):
        return {'intent': self.intent, 'allow_llm': self.allow_llm, 'masked_message': self.message,
                'reply': self.reply, 'agent': AGENT}


def known_place(text):
    text = text.strip().rstrip('!?')
    if not re.fullmatch(r"[\w\s,.'()\-]+", text) or re.search(
            r'\b(?:what|why|how|who|write|tell|explain|solve|teach|calculate|give|ignore)\b', text, re.I):
        return False
    first = text.split(',')[0].strip().casefold()
    if first in _CITIES:
        return True
    try:
        return bool(destination_route(text).get('region_id'))
    except ValueError:
        # The destination policy will ask about an invalid/foreign qualifier;
        # keep it on the travel path instead of dropping the traveller's details.
        return any(first == r['name'].casefold() for r in directory()['regions'])


def evaluate(message, *, question='', details=None, submitted=None):
    """Classify before extraction/geocoding/planning; structured fields don't
    turn an explicitly unrelated or abusive message into a travel question.
    """
    details, submitted = details or {}, submitted or {}
    clean = mask_text(message)
    text = normalize(message).strip()
    if has_abuse(message) or has_abuse(submitted):
        return Decision('abusive', False, clean, PROFESSIONAL_REPLY)
    plain = re.sub(r'[!?.,]+$', '', text.casefold()).strip()
    plain = re.sub(r'\s+', ' ', plain)
    if plain in _GREETINGS:
        return Decision('greeting', False, clean, _GREETINGS[plain] + ' How can I help with your travel plans in India?')
    greeting = re.fullmatch(r'(hi|hello|hey|good morning|good afternoon|good evening|namaste)[\s,!.-]+'
                            r'(?:there|tripweave|how are you|can you help me|how are you doing)', plain)
    if greeting:
        return Decision('greeting', False, clean, _GREETINGS[greeting[1]] + ' How can I help with your travel plans in India?')
    if plain in {'help', 'help me', 'what can you do', 'who are you'}:
        return Decision('help', False, clean, 'I’m TripWeave, your travel guide for India. '
                        'I can help with destinations, itineraries, weather, food, stays and transport. Where would you like to go?')
    if _OFF_TOPIC.search(text):
        return Decision('non_travel', False, clean, TRAVEL_FALLBACK)
    # Existing deterministic editor/recovery commands never require intent AI.
    if text in {'Apply trip details', 'Retry saved turn', 'Build my plan using flexible preferences for any missing optional details.'}:
        return Decision('travel', True, clean)
    if _TRAVEL.search(text) or _TRAVEL_PHRASE.search(text):
        return Decision('travel', True, clean)
    if submitted and re.match(r'^(?:please\s+)?(?:use|change|switch|update|set|prefer)\b', text, re.I) and any(
            isinstance(submitted.get(k), str) and known_place(submitted[k]) for k in ('destination', 'origin')):
        return Decision('trip_detail', True, clean)
    if details and submitted and re.match(r'^(?:please\s+)?(?:make|change|update|set|use)\b', text, re.I) and re.search(
            r'\b(?:days?|dates?|hours?|start|finish|budget|currency|interests?|companions?|departure|return)\b', text, re.I):
        return Decision('trip_detail', True, clean)
    if details.get('destination') and re.fullmatch(r'(?:please )?(?:make it|make the trip|make the plan) '
            r'(?:cheaper|shorter|longer|more relaxed|more adventurous|less crowded)[.!]?', plain):
        return Decision('travel_followup', True, clean)
    if details.get('destination') and re.search(r'\b(?:add|remove|change|extend|reduce|skip|replace|reorder)\b', text, re.I) and re.search(
            r'\b(?:days?|nights?|stops?|activities|visits?)\b', text, re.I):
        return Decision('travel_followup', True, clean)
    if known_place(text) or re.search(r'\b(?:from|to|in)\s+([\w ,.-]+)', text, re.I) and any(
            re.search(r'\b' + re.escape(city) + r'\b', text, re.I) for city in _CITIES):
        return Decision('destination', True, clean)
    # Format-constrained answers remain usable during a clarification flow.
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{1,2}\s*(?:days?)?|\d{2}:\d{2}', text, re.I):
        return Decision('trip_detail', True, clean)
    if question == 'currency' and re.fullmatch(r'[A-Za-z]{3}', text):
        return Decision('trip_detail', True, clean)
    if question == 'start_date' and re.fullmatch(r'(?:today|tomorrow|next week|next month|'
            r'(?:(?:next|this) )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|in \d+ days?)', plain):
        return Decision('trip_detail', True, clean)
    if question == 'days' and re.fullmatch(r'(?:one|two|three|four|five|six|seven)(?: days?)?', plain):
        return Decision('trip_detail', True, clean)
    if question == 'budget' and re.fullmatch(r'(?:flexible|no fixed budget|\d[\d,. ]*(?:[kK])?(?:\s*[A-Za-z]{3})?)', text, re.I):
        return Decision('trip_detail', True, clean)
    if question == 'companions' and re.fullmatch(r'(?:solo|alone|couple|friends|family|family of \d+|'
            r'\d+ (?:adults?|people|friends|child(?:ren)?|kids?)(?: and \d+ (?:adults?|child(?:ren)?|kids?))?)', text, re.I):
        return Decision('trip_detail', True, clean)
    if question in {'origin', 'destination'} and len(text) <= 200 and len(text.split()) <= 8 and re.fullmatch(r"[\w\s,.'()\-]+", text) and not re.search(r'\b(?:what|why|how|who|write|tell|explain|solve|teach|calculate|make|give)\b', text, re.I):
        return Decision('trip_detail', True, clean)
    if question == 'interests' and re.fullmatch(r'(?:history|nature|food|relaxation|relaxed|walking|culture|adventure|shopping|photography|art|beaches|wildlife|and|,|\s)+', plain):
        return Decision('trip_detail', True, clean)
    if submitted and plain in {'apply', 'update', 'continue', 'yes', 'ok', 'okay'}:
        return Decision('trip_detail', True, clean)
    if plain in {'yes', 'no', 'ok', 'okay', 'sure', 'continue', 'go ahead', 'please do', 'sounds good'} and details:
        if not question and details.get('destination') and details.get('origin'):
            return Decision('travel_followup', True, clean)
        return Decision('clarification', False, clean, 'Please answer the pending trip question so we can continue.')
    return Decision('non_travel', False, clean, TRAVEL_FALLBACK if re.search(r'\b(?:what|who|why|how|write|tell|solve|explain)\b', text, re.I) else CLARIFY_REPLY)
