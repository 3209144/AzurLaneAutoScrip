from module.campaign.campaign_base import CampaignBase
from module.logger import logger
from module.map.map_base import CampaignMap
from module.map.map_grids import RoadGrids, SelectedGrids

MAP = CampaignMap()
MAP = CampaignMap('sp1')
MAP.shape = 'h5'
MAP.map_data = '''
    ++ ++ ++ -- ME ME MB ++
    -- -- -- ME -- ME -- --
    -- -- ++ -- ME ++ MB --
    SP SP -- ME -- ++ -- ME
    SP SP -- -- ME -- ME --
'''
MAP.camera_data = ['D3', 'D5']
MAP.spawn_data = [
    {'battle': 0, 'enemy': 3},
    {'battle': 1, 'enemy': 1},
    {'battle': 2, 'enemy': 1},
    {'battle': 3, 'enemy': 1},
    {'battle': 4, 'boss': 1},
]


class Config:
    SUBMARINE = 0
    FLEET_BOSS = 0

    MAP_HAS_AMBUSH = False


class Campaign(CampaignBase):
    MAP = MAP

    def battle_0(self):
        return self.battle_default()

    def battle_4(self):
        return self.brute_clear_boss()
