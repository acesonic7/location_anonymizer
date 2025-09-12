# 🔒 Location Data Anonymizer

<img width="4769" height="2367" alt="image" src="https://github.com/user-attachments/assets/723c6733-e25b-44b8-a735-8696e2c7fa3b" />


**Privacy-preserving location data anonymization tool with home-based protection.**

Developed by **MobyX** in the context of the **SPINE project** for secure location data sharing and privacy protection in research.

## 📋 Overview

This tool anonymizes personal location traces from JSON datasets, mostly coming from Citizen app tracking data, by applying intelligent coordinate scrambling around a user-designated home location. It maintains spatial relationships for data utility while protecting privacy through global coordinate shifting and proximity-based noise injection.


## ✨ Features

- 🏠 **Home-Based Anonymization** -  Protection/scramble around  home location
- 🌍 **Global Coordinate Shifting** - Moves all locations by a random offset
- 🔊 **Proximity-Based Noise** - More scrambling near sensitive areas
- 📊 **Before/After Visualization** - See exactly how your data is protected
- 🔒 **Complete Privacy** - Original coordinates never retained in output
- 📁 **JSON Structure Preserved** - Only location coordinates are modified

## 🔧 How It Works

1. **Identifies your home** using the predefined home activity ID
2. **Applies global shift** - Moves all coordinates by 1-10km randomly
3. **Adds targeted noise** - Extra randomization within configurable radius of home
4. **Preserves relationships** - Maintains relative distances and movement patterns
5. **Generates visualization** - Shows before/after comparison for verification

## 📦 Installation & Setup

### Requirements
- Python 3.11 or higher
- matplotlib
- numpy

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/acesonic7/location_anonymizer.git
cd location_anonymizer

# 2. Install dependencies
pip install matplotlib numpy

# 3. Verify installation
python location_anonymizer.py --help
```

## 🚀 Usage

### Basic Usage

```bash
python location_anonymizer.py input.json output.json "19ac8d10-e85e-11ea-9c89-eb597145d8d6"
```

### With Custom Settings

```bash
python location_anonymizer.py input.json output.json "19ac8d10-e85e-11ea-9c89-eb597145d8d6" --radius 0.8 --noise 0.4 --viz demo.png
```

### Skip Visualization (Faster Processing)

```bash
python location_anonymizer.py input.json output.json "19ac8d10-e85e-11ea-9c89-eb597145d8d6" --no-viz
```

### Parameters

| Parameter | Description | Default | Range |
|-----------|-------------|---------|--------|
| `--radius` | Anonymization radius around home (km) | 0.5 | 0.1-5.0 |
| `--noise` | Noise intensity factor | 0.3 | 0.1-1.0 |
| `--viz` | Save visualization to specific file | auto-generated | any path |
| `--no-viz` | Skip visualization creation | false | flag |

## 📊 Complete Example

```bash
# Anonymize with high privacy settings and save visualization
python location_anonymizer.py MyLocationData.json MyLocationData_anonymized.json "19ac8d10-e85e-11ea-9c89-eb597145d8d6" --radius 0.8 --noise 0.6 --viz privacy_demo.png

# Output:
# ✓ Found home location: 40.712776, -74.005974
# ✓ Applying global coordinate offset: 0.045123°, -0.078456°
# ✓ Processed 2847 valid location points
# ✓ 156 points within anonymization radius received extra noise
# ✓ VERIFICATION PASSED: All 2847 coordinates successfully anonymized
# ✓ Anonymized data saved successfully!
# ✓ Visualization saved to: privacy_demo.png
```

## 📊 Input/Output

### Input Format
JSON file with this structure:
```json
{
  "locations": [...],      // Location records with lat/lon coordinates
  "places": [...],         // Places including home location
  "geoFence": [...],       // Geofence events (unchanged)
  "userMobilities": [...], // User mobility data (unchanged)  
  "predictions": [...]     // Predictions (unchanged)
}
```

### Output Format
Identical JSON structure with **anonymized coordinates** in the `locations` array. All other data remains unchanged.

**Original location:**
```json
{"latitude": 40.712776, "longitude": -74.005974}
```

**Anonymized location:**
```json
{"latitude": 40.698234, "longitude": -73.991847}
```

## 📁 Project Structure

```
location-anonymizer/
├── location_anonymizer.py    # Main anonymization script
├── find_home_id.py          # Helper script (for development)
├── requirements.txt         # Python dependencies
├── README.md               # This file
└── examples/               # Example files and outputs
```

## 🔒 Privacy Guarantees

- ✅ **No original coordinates in output** - Completely replaced with anonymized versions
- ✅ **Irreversible transformation** - Cannot recover original locations from output  
- ✅ **Global coordinate shift** - Entire dataset moved 1-10km randomly
- ✅ **Home-area protection** - Extra noise within configurable radius of home
- ✅ **Verification system** - Confirms no original coordinates remain

## 📊 Visualization

The tool generates before/after visualizations showing:
- **Left panel:** Original location data centered on actual home
- **Right panel:** Anonymized data with coordinate shifts and noise
- **Statistics:** Details about anonymization parameters and affected points
- **Visual indicators:** Home location, anonymization radius, and data points

## 🐛 Troubleshooting

### "Home location not found"
- Ensure your JSON file contains the expected places structure
- Verify the home activity ID exists in your data

### "matplotlib not available"
```bash
pip install matplotlib numpy
```

### Permission issues
```bash
# Make sure you have write permissions in the output directory
chmod 755 output_directory/
```

## 📄 About

### SPINE Project
This tool was developed as part of the SPINE (Sustainable Personal Indoor and Outdoor Navigation Experience) project, which focuses on advancing public transport and sustainable transportation .

### MobyX
**MobyX** is a research team specializing in mobility data analytics and sustainable transportation solutions.

### License
This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Contact

For questions, issues, or collaboration opportunities related to the SPINE project or location data anonymization:
- Open an issue on GitHub
- Contact the MobyX development team
- Check the troubleshooting section above

---

**⚠️ Important:** Always verify your anonymized data meets your privacy requirements before sharing. This tool provides technical anonymization but cannot guarantee complete privacy in all scenarios. Use responsibly.
