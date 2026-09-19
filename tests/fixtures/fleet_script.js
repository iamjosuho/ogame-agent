
    var checkTargetUrl = "https:\/\/s1-en.ogame.gameforge.com\/game\/index.php?page=ingame&component=fleetdispatch&action=checkTarget&asJson=1"
    var sendFleetUrl = "https:\/\/s1-en.ogame.gameforge.com\/game\/index.php?page=ingame&component=fleetdispatch&action=sendFleet&asJson=1"
    var saveSettingsUrl = "https:\/\/s1-en.ogame.gameforge.com\/game\/index.php?page=ingame&component=fleetdispatch&action=saveFleetBoxOrderSettings&asJson=1"

    var fleetBoxOrder = {"fleetboxdestination":0,"fleetboxmission":1,"fleetboxbriefingandresources":2}

    var FLEET_DEUTERIUM_SAVE_FACTOR = 0.6;
    var maxNumberOfPlanets = 2;
    var shipsData = {"202":{"id":202,"name":"\u5c0f\u578b\u904b\u8f38\u8266","baseCargoCapacity":6250,"baseFuelCapacity":6250,"fuelConsumption":6,"speed":12000},"203":{"id":203,"name":"\u5927\u578b\u904b\u8f38\u8266","baseCargoCapacity":31250,"baseFuelCapacity":31250,"fuelConsumption":30,"speed":18000},"204":{"id":204,"name":"\u8f15\u578b\u6230\u9b25\u6a5f","baseCargoCapacity":50,"baseFuelCapacity":50,"fuelConsumption":12,"speed":17500},"205":{"id":205,"name":"\u91cd\u578b\u6230\u9b25\u6a5f","baseCargoCapacity":100,"baseFuelCapacity":100,"fuelConsumption":45,"speed":16000},"206":{"id":206,"name":"\u5de1\u6d0b\u8266","baseCargoCapacity":800,"baseFuelCapacity":800,"fuelConsumption":180,"speed":24000},"207":{"id":207,"name":"\u6230\u5217\u8266","baseCargoCapacity":1500,"baseFuelCapacity":1500,"fuelConsumption":300,"speed":10000},"208":{"id":208,"name":"\u6b96\u6c11\u8239","baseCargoCapacity":7500,"baseFuelCapacity":7500,"fuelConsumption":600,"speed":4000},"209":{"id":209,"name":"\u56de\u6536\u8239","baseCargoCapacity":20000,"baseFuelCapacity":20000,"fuelConsumption":180,"speed":2800},"210":{"id":210,"name":"\u9593\u8adc\u885b\u661f","baseCargoCapacity":0,"baseFuelCapacity":5,"fuelConsumption":1,"speed":140000000},"211":{"id":211,"name":"\u5c0e\u5f48\u8266","baseCargoCapacity":500,"baseFuelCapacity":500,"fuelConsumption":420,"speed":6400},"213":{"id":213,"name":"\u6bc0\u6ec5\u8005","baseCargoCapacity":2000,"baseFuelCapacity":2000,"fuelConsumption":600,"speed":5000},"214":{"id":214,"name":"\u6b7b\u661f","baseCargoCapacity":1000000,"baseFuelCapacity":1000000,"fuelConsumption":1,"speed":100},"215":{"id":215,"name":"\u6230\u9b25\u5de1\u6d0b\u8266","baseCargoCapacity":750,"baseFuelCapacity":750,"fuelConsumption":150,"speed":10000},"218":{"id":218,"name":"\u60e1\u9b54\u98db\u8239","baseCargoCapacity":10000,"baseFuelCapacity":10000,"fuelConsumption":660,"speed":7000},"219":{"id":219,"name":"\u63a2\u8def\u8005","baseCargoCapacity":10000,"baseFuelCapacity":10000,"fuelConsumption":180,"speed":12000}};

    var PLAYER_ID_SPACE = 99999;
    var PLAYER_ID_LEGOR = 1;
    var DONUT_GALAXY = 1;
    var DONUT_SYSTEM = 1;
    var MAX_GALAXY = 7;
    var MAX_SYSTEM = 499;
    var MAX_POSITION = 16;
    var SPEEDFAKTOR_FLEET_PEACEFUL = 8;
    var SPEEDFAKTOR_FLEET_WAR = 1;
    var SPEEDFAKTOR_FLEET_HOLDING = 1;
    var SPEED_FLEET_MOON_DESTRUCTION = 310;
    var PLANETTYPE_PLANET = 1;
    var PLANETTYPE_DEBRIS = 2;
    var PLANETTYPE_MOON = 3;
    var EXPEDITION_POSITION = 16;
    var MAX_NUMBER_OF_PLANETS = 2;
    var COLONIZATION_ENABLED = true;

    var LOOT_PRIO_METAL = 2;
    var LOOT_PRIO_CRYSTAL = 3;
    var LOOT_PRIO_DEUTERIUM = 4;
    var LOOT_PRIO_FOOD = 1;

    var missions = {"MISSION_NONE":0,"MISSION_ATTACK":1,"MISSION_UNIONATTACK":2,"MISSION_TRANSPORT":3,"MISSION_DEPLOY":4,"MISSION_HOLD":5,"MISSION_ESPIONAGE":6,"MISSION_COLONIZE":7,"MISSION_RECYCLE":8,"MISSION_DESTROY":9,"MISSION_MISSILEATTACK":10,"MISSION_EXPEDITION":15};
    var orderNames = {"15":"\u9060\u5f81\u63a2\u96aa","7":"\u6b96\u6c11","8":"\u63a1\u96c6\u56de\u6536","3":"\u904b\u8f38","4":"\u90e8\u7f72","6":"\u9593\u8adc\u5075\u5bdf","5":"ACS\u806f\u5408\u9632\u79a6","1":"\u653b\u64ca","2":"ACS\u806f\u5408\u653b\u64ca","9":"\u6467\u6bc0\u6708\u7403"};
    var orderDescriptions = {"15":"\u6d3e\u9063\u60a8\u7684\u8266\u968a\u524d\u5f80\u6df1\u9083\u7684\u5b87\u5b99\u7a7a\u9593\u76e1\u982d\u6311\u6230\u6263\u4eba\u5fc3\u5f26\u7684\u9060\u5f81\u63a2\u96aa\u4efb\u52d9.","7":"\u6b96\u6c11\u4e00\u500b\u65b0\u7684\u884c\u661f.","8":"\u6d3e\u9063\u60a8\u7684\u56de\u6536\u8239\u5230\u4e00\u7247\u5ee2\u589f\u63a1\u96c6\u6f02\u6d6e\u5728\u90a3\u88e1\u7684\u8cc7\u6e90.","3":"\u904b\u9001\u60a8\u7684\u8cc7\u6e90\u81f3\u5176\u5b83\u884c\u661f.","4":"\u5c07\u60a8\u7684\u8266\u968a\u6c38\u4e45\u90e8\u7f72\u81f3\u60a8\u5e1d\u570b\u5167\u7684\u53e6\u4e00\u884c\u661f.","6":"\u5c0d\u5176\u5b83\u5e1d\u570b\u9032\u884c\u9593\u8adc\u5075\u5bdf.","5":"\u5354\u540c\u9632\u79a6\u60a8\u968a\u53cb\u7684\u884c\u661f.","1":"\u653b\u64ca\u8266\u968a\u4e26\u9632\u79a6\u6575\u4eba.","2":"\u82e5\u5be6\u529b\u5f37\u5927\u7684\u73a9\u5bb6\u900f\u904eACS\u52a0\u5165,\u9ad4\u9762\u6230\u9b25\u5c07\u53ef\u80fd\u8b8a\u6210\u5931\u683c\u6230\u9b25.\u653b\u64ca\u65b9\u7684\u8ecd\u4e8b\u5206\u6578\u7e3d\u8a08\u8207\u9632\u79a6\u65b9\u8ecd\u4e8b\u5206\u6578\u7e3d\u8a08\u7684\u6bd4\u8f03\u503c,\u5728\u9019\u88e1\u5c07\u662f\u6c7a\u5b9a\u6027\u56e0\u7d20.","9":"\u6467\u6bc0\u6575\u4eba\u7684\u6708\u7403."};

    var currentPlanet = {"galaxy":1,"system":1,"position":1,"type":1,"name":"Homeworld"};
    var targetPlanet = {"galaxy":1,"system":1,"position":1,"type":1,"name":"Homeworld"};
    var shipsOnPlanet = [{"id":202,"number":2},{"id":203,"number":0},{"id":204,"number":1},{"id":205,"number":0},{"id":206,"number":0},{"id":207,"number":0},{"id":208,"number":1},{"id":209,"number":0},{"id":210,"number":2},{"id":211,"number":0},{"id":213,"number":0},{"id":214,"number":0},{"id":215,"number":0},{"id":218,"number":0},{"id":219,"number":0}];
    var useHalfSteps = false;
    var shipsToSend = [];
    var planets = [{"galaxy":1,"system":1,"position":1,"type":1,"name":"Homeworld"}];
    var standardFleetTemplates = [];
    var expeditionFleetTemplates = [];
    var unions = [];

    var mission = 0;
    var unionID = 0;
    var speed = 10;

    var missionHold = 5;
    var missionExpedition = 15;

    var holdingTime = 1;
    var expeditionTime = 0;

    var metalOnPlanet = 14986;
    var crystalOnPlanet = 24465;
    var deuteriumOnPlanet = 10103;
    var foodOnPlanet = 0;

    var fleetCount = 0;
    var maxFleetCount = 5;
    var expeditionCount = 0;
    var maxExpeditionCount = 1;

    var warningsEnabled = true;

    var playerId = 999999;
    var hasAdmiral = false;
    var hasCommander = false;
    var isOnVacation = false;

    var moveInProgress = false;
    var planetCount = 1;

    var loca = {"LOCA_ALL_OVERVIEW":"\u6982\u89bd","LOCA_ALL_AJAXLOAD":"\u8f09\u5165\u4e2d...","LOCA_ALL_CANCEL":"\u53d6\u6d88","LOCA_ALL_MOVE":"\u9077\u79fb","LOCA_PLANETMOVE_COOLDOWN_TOOLTIP":"\u53ef\u9032\u884c\u4e0b\u6b21\u9077\u79fb\u7684\u6642\u9593","LOCA_PLANETMOVE_NOT_ON_MOON":"\u9077\u79fb\u7121\u6cd5\u5f9e\u6708\u7403\u4e0a\u57f7\u884c.","LOCA_LINK_TO_GALAXY":"\u524d\u5f80\u9280\u6cb3\u7cfb","LOCA_OVERVIEW_PLANETMOVE_FREE_TOOLTIP":"\u53ef\u7528\u7684\u514d\u8cbb\u884c\u661f\u9077\u79fb","LOCA_OVERVIEW_RENAME_GIVEUP":"\u5ee2\u68c4\/\u91cd\u547d\u540d","LOCA_FLEET_TITLE_MOVEMENTS":"\u524d\u5f80\u8266\u968a\u52d5\u5411","LOCA_FLEET_MOVEMENT":"\u8266\u968a\u52d5\u5411","LOCA_FLEET_EDIT_STANDARTFLEET":"\u7de8\u8f2f\u6a19\u6e96\u8266\u968a","LOCA_EXPEDITION_FLEET_TEMPLATE":"\u9060\u5f81\u8266\u968a","LOCA_FLEET_STANDARD":"\u6a19\u6e96\u8266\u968a","LOCA_FLEET_HEADLINE_ONE":"\u6d3e\u9063\u8266\u968a I","LOCA_FLEET_TOOLTIPP_SLOTS":"\u5df2\u4f7f\u7528\u8266\u968a\u6307\u63ee\u6b0a\u6578\/\u8266\u968a\u6307\u63ee\u6b0a\u6578\u7e3d\u8a08","LOCA_FLEET_FLEETSLOTS":"\u8266\u968a","LOCA_FLEET_NO_FREE_SLOTS":"\u6c92\u6709\u53ef\u7528\u7684\u8266\u968a\u6307\u63ee\u6b0a","LOCA_FLEETSENDING_NO_TARGET":"\u60a8\u8981\u9078\u64c7\u4e00\u500b\u6709\u6548\u76ee\u6a19.","LOCA_FLEET_TOOLTIPP_EXP_SLOTS":"\u5df2\u4f7f\u7528\u9060\u5f81\u63a2\u96aa\u6307\u63ee\u6b0a\u6578\/\u9060\u5f81\u63a2\u96aa\u6307\u63ee\u6b0a\u6578\u7e3d\u8a08","LOCA_FLEET_EXPEDITIONS":"\u9060\u5f81\u8266\u968a","LOCA_ALL_NEVER":"\u6c38\u4e0d","LOCA_FLEET_SEND_NOTAVAILABLE":"\u8266\u968a\u7121\u6cd5\u6d3e\u9063","LOCA_FLEET_NO_SHIPS_ON_PLANET":"\u8a72\u884c\u661f\u4e0a\u6c92\u6709\u8266\u8239.","LOCA_SHIPYARD_HEADLINE_BATTLESHIPS":"\u6230\u9b25\u8266\u8239","LOCA_SHIPYARD_HEADLINE_CIVILSHIPS":"\u6c11\u7528\u8266\u8239","LOCA_FLEET_SELECT_SHIPS_ALL":"\u9078\u64c7\u5168\u90e8\u8266\u8239","LOCA_FLEET_SELECTION_RESET":"\u91cd\u65b0\u9078\u64c7","LOCA_API_FLEET_DATA":"\u8a72\u8cc7\u6599\u53ef\u88ab\u8f38\u5165\u81f3\u517c\u5bb9\u7684\u6230\u9b25\u6a21\u64ec\u5668\u5167:","LOCA_ALL_BUTTON_FORWARD":"\u4e0b\u4e00\u6b65","LOCA_FLEET_NO_SELECTION":"\u672a\u6709\u9078\u64c7\u4efb\u4f55\u8266\u968a","LOCA_ALL_TACTICAL_RETREAT":"\u6230\u8853\u64a4\u9000","LOCA_FLEET1_TACTICAL_RETREAT_CONSUMPTION_TOOLTIP":"\u986f\u793a\u6bcf\u6b21\u64a4\u9000\u7684\u91cd\u6c2b\u4f7f\u7528\u91cf","LOCA_FLEET_FUEL_CONSUMPTION":"\u91cd\u6c2b\u71c3\u6599\u6d88\u8017\u91cf","LOCA_FLEET_ERROR_OWN_VACATION":"\u5047\u671f\u6a21\u5f0f\u4e2d\u4e0d\u80fd\u6d3e\u9063\u8266\u968a!","LOCA_FLEET_CURRENTLY_OCCUPIED":"\u8266\u968a\u7576\u524d\u5728\u6230\u9b25\u4e2d\u3002","LOCA_FLEET_FREE_MARKET_SLOTS":"\u5831\u50f9","LOCA_FLEET_TOOLTIPP_FREE_MARKET_SLOTS":"\u5df2\u4f7f\u7528\/\u7e3d\u8a08\u8cbf\u6613\u8266\u968a","LOCA_FLEET_HEADLINE_TWO":"\u6d3e\u9063\u8266\u968a II","LOCA_FLEET_TAKEOFF_PLACE":"\u96e2\u958b\u6240\u5728\u5730","LOCA_FLEET_TARGET_PLACE":"\u76ee\u7684\u5730","LOCA_ALL_PLANET":"\u884c\u661f","LOCA_ALL_MOON":"\u6708\u7403","LOCA_FLEET_COORDINATES":"\u5ea7\u6a19","LOCA_FLEET_DISTANCE":"\u8ddd\u96e2","LOCA_FLEET_DEBRIS":"\u5ee2\u589f","LOCA_FLEET_SHORTLINKS":"\u6377\u5f91","LOCA_FLEET_FIGHT_ASSOCIATION":"\u4f5c\u6230\u52e2\u529b","LOCA_FLEET_BRIEFING":"\u7c21\u5831","LOCA_FLEET_DURATION_ONEWAY":"\u98db\u884c\u6642\u9593(\u55ae\u7a0b)","LOCA_FLEET_SPEED":"\u901f\u5ea6:","LOCA_FLEET_SPEED_MAX_SHORT":"\u6700\u591a","LOCA_FLEET_ARRIVAL":"\u5230\u9054","LOCA_FLEET_TIME_CLOCK":"\u5c0f\u6642","LOCA_FLEET_RETURN":"\u8fd4\u56de","LOCA_FLEET_HOLD_FREE":"\u53ef\u8f09\u8ca8\u5bb9\u91cf","LOCA_ALL_BUTTON_BACK":"\u8fd4\u56de","LOCA_FLEET_PLANET_UNHABITATED":"\u7121\u4eba\u5c45\u4f4f\u7684\u884c\u661f","LOCA_FLEET_NO_DEBIRS_FIELD":"\u6c92\u6709\u5ee2\u589f","LOCA_FLEET_PLAYER_UMODE":"\u73a9\u5bb6\u8655\u65bc\u5047\u671f\u6a21\u5f0f\u4e2d","LOCA_FLEET_ADMIN":"\u904a\u6232\u7ba1\u7406\u54e1\u6216\u904a\u6232\u7dad\u8b77\u54e1","LOCA_ALL_NOOBSECURE":"\u65b0\u624b\u4fdd\u8b77","LOCA_GALAXY_ERROR_STRONG":"\u7531\u65bc\u8a72\u73a9\u5bb6\u904e\u65bc\u5f37\u5927,\u8a72\u884c\u661f\u7121\u6cd5\u653b\u64ca!","LOCA_FLEET_NO_MOON":"\u6c92\u6709\u6708\u7403","LOCA_FLEET_NO_RECYCLER":"\u6c92\u6709\u56de\u6536\u8239","LOCA_ALL_NO_EVENT":"\u73fe\u5728\u66ab\u7121\u4efb\u4f55\u6d3b\u52d5\u9032\u884c\u4e2d.","LOCA_PLANETMOVE_ERROR_ALREADY_RESERVED":"\u8a72\u884c\u661f\u4f4d\u7f6e\u5df2\u4fdd\u7559\u7d66\u4e00\u500b\u5c07\u8981\u9077\u79fb\u7684\u884c\u661f.","LOCA_FLEET_ERROR_TARGET_MSG":"\u8266\u968a\u7121\u6cd5\u6d3e\u9063\u81f3\u6b64\u76ee\u6a19.","LOCA_FLEETSENDING_NOT_ENOUGH_FOIL":"\u91cd\u6c2b\u4e0d\u8db3!","LOCA_FLEET_HEADLINE_THREE":"\u6d3e\u9063\u8266\u968a III","LOCA_FLEET_TARGET_FOR_MISSION":"\u70ba\u76ee\u7684\u5730\u9078\u64c7\u4efb\u52d9","LOCA_FLEET_MISSION":"\u4efb\u52d9","LOCA_FLEET_RESOURCE_LOAD":"\u88dd\u8f09\u8cc7\u6e90","LOCA_FLEET_SELECTION_NOT_AVAILABLE":"\u60a8\u7121\u6cd5\u555f\u52d5\u8a72\u4efb\u52d9.","LOCA_FLEET_RETREAT_AFTER_DEFENDER_RETREAT_TOOLTIP":"\u5047\u82e5\u958b\u5553\u8a72\u9078\u9805,\u5982\u679c\u60a8\u7684\u6575\u4eba\u9003\u812b,\u90a3\u60a8\u7684\u8266\u968a\u5c07\u81ea\u52d5\u89e3\u9664\u6230\u9b25\u64a4\u9000.","LOCA_FLEET_RETREAT_AFTER_DEFENDER_RETREAT":"\u9632\u79a6\u65b9\u9003\u812b\u5f8c\u81ea\u884c\u8fd4\u56de","LOCA_FLEET_TARGET":"\u76ee\u7684\u5730","LOCA_FLEET_DURATION_FEDERATION":"\u6230\u9b25\u6642\u9577(\u806f\u5408\u8266\u968a)","LOCA_ALL_TIME_HOUR":"\u6642","LOCA_FLEET_HOLD_TIME":"\u99d0\u7559\u6642\u9593","LOCA_FLEET_EXPEDITION_TIME":"\u9060\u5f81\u63a2\u96aa\u6642\u9593","LOCA_ALL_METAL":"\u91d1\u5c6c","LOCA_ALL_CRYSTAL":"\u6676\u9ad4","LOCA_ALL_DEUTERIUM":"\u91cd\u6c2b","LOCA_ALL_FOOD":"\u98df\u7269","LOCA_FLEET_LOAD_ROOM":"\u8ca8\u8259","LOCA_FLEET_CARGO_SPACE":"\u53ef\u7528\u5009\u5132\u7a7a\u9593\/\u6700\u5927\u5009\u5132\u7a7a\u9593","LOCA_FLEET_SEND":"\u6d3e\u9063\u8266\u968a","LOCA_ALL_NETWORK_ATTENTION":"\u8b66\u544a","LOCA_PLANETMOVE_BREAKUP_WARNING":"\u8b66\u544a! \u8a72\u4efb\u52d9\u5728\u9077\u79fb\u671f\u9593\u5553\u52d5\u5f8c,\u4ecd\u5c07\u904b\u884c,\u4f46\u7e7c\u7e8c\u9019\u6a23\u7684\u8a71,\u9077\u79fb\u9032\u7a0b\u5c07\u6703\u88ab\u53d6\u6d88.\u60a8\u78ba\u5b9a\u8981\u7e7c\u7e8c\u8a72\u4efb\u52d9\u55ce?","LOCA_ALL_YES":"\u662f","LOCA_ALL_NO":"\u4e0d","LOCA_ALL_NOTICE":"\u53c3\u8003","LOCA_FLEETSENDING_MAX_PLANET_WARNING":"\u8b66\u544a\uff01\u7576\u524d\u6c92\u6709\u66f4\u591a\u884c\u661f\u53ef\u9032\u884c\u6b96\u6c11\u3002\u6bcf\u500b\u6b96\u6c11\u5730\u7684\u5b89\u7f6e\u90fd\u9700\u8981\u7279\u5b9a\u7684\u5929\u9ad4\u7269\u7406\u5b78\u7814\u7a76\u7b49\u7d1a\uff08\u8acb\u67e5\u95b1\u5929\u9ad4\u7269\u7406\u5b78\u8aaa\u660e\uff09\u3002\u60a8\u662f\u5426\u9084\u662f\u8981\u6d3e\u9063\u60a8\u7684\u8266\u968a\uff1f","LOCA_ALL_PLAYER":"\u73a9\u5bb6","LOCA_FLEET_RESOURCES_ALL_LOAD":"\u88dd\u8f09\u5168\u90e8\u7684\u8cc7\u6e90","LOCA_FLEET_RESOURCES_ALL":"\u6240\u6709\u8cc7\u6e90","LOCA_NETWORK_USERNAME":"\u73a9\u5bb6\u540d\u7a31","LOCA_EVENTH_ENEMY_INFINITELY_SPACE":"\u5916\u592a\u7a7a","LOCA_FLEETSENDING_NO_MISSION_SELECTED":"\u6c92\u6709\u9078\u64c7\u4efb\u4f55\u4efb\u52d9!","LOCA_EMPTY_SYSTEMS":"\u6e05\u7a7a\u7cfb\u7d71","LOCA_INACTIVE_SYSTEMS":"\u4e0d\u6d3b\u52d5\u7cfb\u7d71","LOCA_NETWORK_ON":"\u5728\u7dda\u4e2d","LOCA_NETWORK_OFF":"\u95dc\u9589","LOCA_LOOT_FOOD":"\u63a0\u596a\u98df\u7269","LOCA_BASHING_SYSTEM_LIMIT_REACHED_ATTACK_MISSIONS_DISABLED":"\u7531\u65bc\u5c0d\u76ee\u6a19\u653b\u64ca\u592a\u591a\uff0c\u653b\u64ca\u4efb\u52d9\u5df2\u88ab\u53d6\u6d88\u3002"};
    var locadyn = {"locaAllOutlawWarning":"\u60a8\u53ef\u7591\u653b\u64ca\u6bd4\u60a8\u5f37\u7684\u73a9\u5bb6.\u5982\u679c\u60a8\u9019\u6a23\u505a,\u60a8\u7684\u653b\u64ca\u4fdd\u8b77\u5c07\u6703\u95dc\u9589 7 \u5929,\u6240\u6709\u7684\u73a9\u5bb6\u53ef\u653b\u64ca\u60a8\u800c\u6c92\u6709\u4efb\u4f55\u4e0d\u5229\u61f2\u7f70.\u60a8\u78ba\u5b9a\u8981\u7e7c\u7e8c\u55ce?","localBashWarning":"\u5728\u9019\u500b\u5b87\u5b99\u4e2d\uff0c\uff12\uff14\u5c0f\u6642\u5167\u53ea\u5141\u8a31\u9032\u884c0\u6b21\u8972\u64ca\u3002\u672c\u6b21\u8972\u64ca\u53ef\u80fd\u6703\u8d85\u51fa\u6b64\u9650\u5236\u3002\u60a8\u771f\u7684\u5e0c\u671b\u767c\u5c04\u55ce\uff1f","locaOfficerbonusTooltipp":"+ 2 \u8266\u968a\u6307\u63ee\u6b0a\u6578 \u56e0\u70ba\u6709 \u8266\u968a\u53f8\u4ee4"};

    var fleetDispatcher = null;

    var emptySystems = 0;
    var inactiveSystems = 0;

    var lootFoodOnAttack = true;

    $(function(){
        fleetDispatcher = new FleetDispatcher(window);
        fleetDispatcher.init();
    });

    var apiDataJson = {"coords":"1:1:1","characterClassId":1,"allianceClassId":null,"researches":{"109":0,"110":0,"111":5,"114":0,"115":4,"117":3,"118":0},"defenses":{"401":{"amount":13,"weapon":0,"shield":0,"armor":0},"402":{"amount":0,"weapon":0,"shield":0,"armor":0},"403":{"amount":0,"weapon":0,"shield":0,"armor":0},"404":{"amount":0,"weapon":0,"shield":0,"armor":0},"405":{"amount":0,"weapon":0,"shield":0,"armor":0},"406":{"amount":0,"weapon":0,"shield":0,"armor":0},"407":{"amount":0,"weapon":0,"shield":0,"armor":0},"408":{"amount":0,"weapon":0,"shield":0,"armor":0}},"ships":{"202":{"amount":2,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"203":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"204":{"amount":1,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"205":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"206":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"207":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"208":{"amount":1,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"209":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"210":{"amount":2,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"211":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"213":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"214":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"215":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"218":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0},"219":{"amount":0,"weapon":0,"shield":0,"armor":0,"cargo":0,"speed":0,"fuel":0}},"missiles":{"502":{"amount":0},"503":{"amount":0}},"bonuses":{"recycleAttackerFleet":0,"moonChanceIncrease":0,"lifeformProtection":0,"spaceDockExtender":0,"denCapacity":{"metal":0,"crystal":0,"deuterium":0},"characterClassBooster":{"1":0,"2":0,"3":0}},"fleetspeed":10}
    var apiCommonData = {"coords":"1:1:1","characterClassId":1};
    var apiTechData = [{"109":0},{"110":0},{"111":5},{"114":0},{"115":4},{"117":3},{"118":0}];
    var apiDefenseData = [{"401":13},{"402":0},{"403":0},{"404":0},{"405":0},{"406":0},{"407":0},{"408":0}];
    var apiShipBaseData = [{"202":2},{"203":0},{"204":1},{"205":0},{"206":0},{"207":0},{"208":1},{"209":0},{"210":2},{"211":0},{"213":0},{"214":0},{"215":0},{"218":0},{"219":0}];

