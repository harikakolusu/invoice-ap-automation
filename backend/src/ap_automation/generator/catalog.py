"""Hand-authored synthetic reference lists. No external data, no real companies or people."""

# category -> (sku prefix, uom, default tax code, price range USD, qty range, items)
CATALOG = {
    "IT_HARDWARE": ("ITH", "EA", "TX18", (25, 2400), (1, 40), [
        "Laptop 14in i7", "Docking Station USB-C", "Monitor 27in QHD", "Wireless Keyboard",
        "USB-C Hub 7-port", "Network Switch 24P", "SSD 1TB NVMe", "Server RAM 32GB",
        "Wi-Fi Access Point", "Rack UPS 3kVA"]),
    "OFFICE_SUPPLIES": ("OFF", "BOX", "TX12", (3, 120), (5, 200), [
        "A4 Copy Paper 5 reams", "Ballpoint Pens 12pk", "Heavy Duty Stapler", "Toner Cartridge BK",
        "Whiteboard Markers 8pk", "File Folders 50pk", "Desk Organizer", "Sticky Notes 24pk"]),
    "MRO": ("MRO", "EA", "TX18", (3, 320), (5, 300), [
        "Safety Gloves Nitrile", "Hydraulic Oil 20L", "Ball Bearing 6204", "V-Belt A42",
        "Hex Bolts M10 100pk", "Welding Rods 5kg", "Cable Ties 1000pk", "Air Filter Panel"]),
    "PACKAGING": ("PKG", "ROLL", "TX12", (1, 60), (50, 2000), [
        "Corrugated Box Large", "Stretch Film Roll", "Pallet Wrap 500m", "Bubble Wrap Roll",
        "Packing Tape 36pk", "Wooden Pallet EUR"]),
    "RAW_MATERIALS": ("RAW", "KG", "TX05", (2, 380), (10, 800), [
        "Steel Sheet 2mm", "Aluminium Rod 20mm", "Copper Wire 2.5mm", "ABS Pellets 25kg",
        "Epoxy Resin 5L", "PP Granules 25kg"]),
    "FACILITIES_SUPPLIES": ("FAC", "EA", "TX05", (2, 90), (10, 300), [
        "Drinking Water 20L", "Floor Detergent 5L", "Hand Sanitizer 1L", "Paper Towels Case",
        "Coffee Beans 1kg", "Trash Bags 100pk"]),
    "SERVICES": ("SRV", "HR", "TX18", (80, 3800), (1, 12), [
        "IT Consulting Hour", "Equipment Maintenance", "Facility Cleaning Month", "Legal Advisory Hour",
        "Software Subscription", "Freight Charges"]),
}

VENDOR_PREFIX = [
    "Apex", "Nimbus", "Vertex", "Quanta", "Helios", "Boreal", "Cobalt", "Zenith", "Orion", "Lumen",
    "Strata", "Keystone", "Meridian", "Pinnacle", "Summit", "Harbor", "Granite", "Silver", "Falcon", "Atlas",
    "Beacon", "Crescent", "Delta", "Evergreen", "Frontier", "Glacier", "Horizon", "Ironwood", "Juniper", "Kestrel",
    "Lakeside", "Monarch", "Northstar", "Oakridge", "Prairie", "Redwood", "Sierra", "Tidewater", "Unity", "Westbrook",
]
VENDOR_CORE = [
    "Industrial Supply", "Tech Components", "Logistics", "Packaging", "Office Solutions", "Materials",
    "Facility Services", "Electronics", "Metals", "Polymers", "Trading", "Systems", "Distribution",
    "Maintenance", "Equipment",
]
CORE_CATEGORY = {
    "Industrial Supply": "MRO", "Tech Components": "IT_HARDWARE", "Logistics": "PACKAGING",
    "Packaging": "PACKAGING", "Office Solutions": "OFFICE_SUPPLIES", "Materials": "RAW_MATERIALS",
    "Facility Services": "FACILITIES_SUPPLIES", "Electronics": "IT_HARDWARE", "Metals": "RAW_MATERIALS",
    "Polymers": "RAW_MATERIALS", "Systems": "IT_HARDWARE", "Maintenance": "MRO", "Equipment": "MRO",
    # "Trading" / "Distribution" -> random category
}
VENDOR_LEGAL =["Inc.", "LLC", "Ltd", "GmbH", "Pvt Ltd", "Co."]

FIRST = ["Aarav", "Maya", "Liam", "Priya", "Noah", "Elena", "Ravi", "Sofia", "Kenji", "Amara", "Lucas", "Isha",
         "Omar", "Chloe", "Diego", "Hana", "Arjun", "Zara", "Felix", "Nadia", "Theo", "Leila", "Vikram", "Grace"]
LAST = ["Sharma", "Okafor", "Lindqvist", "Tanaka", "Moreau", "Patel", "Novak", "Reyes", "Kowalski", "Haddad",
        "Fischer", "Iyer", "Mensah", "Costa", "Brennan", "Sato", "Varga", "Nair", "Quinn", "Duarte"]

WAREHOUSES = ["WH-NORTH", "WH-SOUTH", "WH-EAST", "WH-WEST"]
