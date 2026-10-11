"""The detective team, in board order."""

from engine.agents.ads import AdsDetective
from engine.agents.deploy import DeployDetective
from engine.agents.funnel import FunnelDetective
from engine.agents.payments import PaymentsDetective
from engine.agents.session import SessionDetective
from engine.agents.voice import VoiceDetective
from engine.agents.world import WorldDetective

DETECTIVES = {
    "funnel": FunnelDetective,
    "deploy": DeployDetective,
    "session": SessionDetective,
    "payments": PaymentsDetective,
    "ads": AdsDetective,
    "voice": VoiceDetective,
    "world": WorldDetective,
}
