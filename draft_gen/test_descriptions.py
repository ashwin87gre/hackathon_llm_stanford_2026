"""Reusable test invention descriptions for patent draft generation."""

TEST_DESCRIPTIONS = [
    # 0: AI / Computer Vision
    (
        "A smart traffic light system that uses cameras and a neural network to detect "
        "the number of vehicles, pedestrians, and cyclists waiting at each approach of "
        "an intersection. The system dynamically adjusts green light duration in real-time "
        "based on current demand, reducing average wait times by prioritizing the busiest "
        "approach while ensuring minimum green times for all directions. It communicates "
        "with neighboring intersections to create green wave corridors along major routes."
    ),

    # 1: Medical Device
    (
        "A wearable patch that continuously monitors blood glucose levels through the skin "
        "without needles, using reverse iontophoresis to extract interstitial fluid. The "
        "patch contains a miniaturized electrochemical biosensor, a Bluetooth Low Energy "
        "transmitter, and a flexible rechargeable battery. It sends readings every 5 minutes "
        "to a smartphone app that uses machine learning to predict glucose trends 30 minutes "
        "ahead and alerts the user before hypo- or hyperglycemic episodes occur."
    ),

    # 2: Sustainability / Energy
    (
        "A modular home battery system that combines second-life electric vehicle batteries "
        "with a smart inverter. The system monitors the health of each battery module "
        "individually, routes power through the healthiest modules first, and automatically "
        "isolates degraded modules. It integrates with rooftop solar panels and the grid, "
        "using time-of-use electricity pricing data to decide when to store, consume, or "
        "sell back energy, maximizing cost savings for the homeowner."
    ),

    # 3: Robotics / Manufacturing
    (
        "A robotic arm attachment that can be mounted on any standard industrial robot and "
        "enables it to perform precision soldering on circuit boards. The attachment includes "
        "a high-resolution thermal camera for real-time solder joint inspection, an automatic "
        "solder wire feeder, and a closed-loop temperature controller that adjusts iron "
        "temperature based on the thermal mass of the component being soldered. A vision "
        "system identifies component positions from the board's CAD file and plans the "
        "optimal soldering sequence to minimize thermal stress."
    ),

    # 4: Consumer / Software
    (
        "A mobile app that uses augmented reality to help people with food allergies shop "
        "safely in grocery stores. The user points their phone camera at any packaged food "
        "product, and the app reads the ingredient list using OCR, cross-references it "
        "against the user's allergy profile, and displays a real-time AR overlay showing "
        "a green checkmark for safe products or a red warning with the specific allergen "
        "highlighted. It also suggests safe alternative products available in the same store "
        "by querying the store's inventory API."
    ),
]
