import json
import random
import math
import copy
from typing import Dict, List, Tuple, Optional
import argparse
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime


class LocationAnonymizer:
    def __init__(self, home_primary_activity_id: str, anonymization_radius_km: float = 0.5, noise_factor: float = 0.3):
        """
        Initialize the location anonymizer.

        Args:
            home_primary_activity_id: The primary activity ID that identifies the home location
            anonymization_radius_km: Radius in kilometers around home to apply anonymization
            noise_factor: Factor controlling the amount of noise added (0.1 = low noise, 1.0 = high noise)
        """
        self.home_primary_activity_id = home_primary_activity_id
        self.anonymization_radius_km = anonymization_radius_km
        self.noise_factor = noise_factor
        self.home_location = None
        self.coordinate_offset = None
        self.original_locations = []
        self.anonymized_locations = []

    def haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate the great circle distance between two points on Earth in kilometers.
        """
        R = 6371  # Earth's radius in kilometers

        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def find_home_location(self, data: Dict) -> Optional[Tuple[float, float]]:
        """
        Find the home location based on the primary activity ID.
        """
        places = data.get('places', [])

        for place in places:
            if place.get('primaryActivityId') == self.home_primary_activity_id:
                lat = place.get('latitude')
                lon = place.get('longitude')
                if lat is not None and lon is not None:
                    print(f"Found home location: {lat:.6f}, {lon:.6f}")
                    return (lat, lon)

        print(f"Warning: Home location with primaryActivityId '{self.home_primary_activity_id}' not found!")
        return None

    def generate_coordinate_offset(self) -> Tuple[float, float]:
        """
        Generate a random offset for all coordinates to maintain relative positions
        while obscuring absolute location.
        """
        # Generate random offset within a reasonable range (up to 10km)
        offset_distance = random.uniform(1, 10)  # km
        offset_bearing = random.uniform(0, 360)  # degrees

        # Convert to lat/lon offset (approximate)
        lat_offset = (offset_distance * math.cos(math.radians(offset_bearing))) / 111.32
        lon_offset = (offset_distance * math.sin(math.radians(offset_bearing))) / (
                    111.32 * math.cos(math.radians(self.home_location[0])))

        return (lat_offset, lon_offset)

    def add_noise_to_coordinates(self, lat: float, lon: float, distance_from_home: float) -> Tuple[float, float]:
        """
        Add noise to coordinates based on distance from home and noise factor.
        """
        if distance_from_home > self.anonymization_radius_km:
            return lat, lon

        # Calculate noise intensity (higher near home)
        noise_intensity = self.noise_factor * (1 - distance_from_home / self.anonymization_radius_km)

        # Add random noise (approximately 100m * noise_intensity)
        max_noise_km = 0.1 * noise_intensity

        noise_lat = random.uniform(-max_noise_km, max_noise_km) / 111.32
        noise_lon = random.uniform(-max_noise_km, max_noise_km) / (111.32 * math.cos(math.radians(lat)))

        return lat + noise_lat, lon + noise_lon

    def anonymize_coordinates(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Apply anonymization to a single coordinate pair.
        """
        if self.home_location is None:
            return lat, lon

        # Calculate distance from home
        distance_from_home = self.haversine_distance(
            lat, lon, self.home_location[0], self.home_location[1]
        )

        # Apply global offset
        new_lat = lat + self.coordinate_offset[0]
        new_lon = lon + self.coordinate_offset[1]

        # Add noise if near home
        new_lat, new_lon = self.add_noise_to_coordinates(new_lat, new_lon, distance_from_home)

        return new_lat, new_lon

    def anonymize_locations_array(self, locations: List[Dict]) -> List[Dict]:
        """
        Anonymize all locations in the locations array.
        """
        anonymized_locations = []

        for location in locations:
            new_location = copy.deepcopy(location)

            if 'latitude' in location and 'longitude' in location:
                lat = location['latitude']
                lon = location['longitude']

                if lat is not None and lon is not None:
                    # Store original coordinates for visualization
                    self.original_locations.append((lat, lon))

                    new_lat, new_lon = self.anonymize_coordinates(lat, lon)
                    new_location['latitude'] = new_lat
                    new_location['longitude'] = new_lon

                    # Store anonymized coordinates for visualization
                    self.anonymized_locations.append((new_lat, new_lon))
                else:
                    # Handle case where coordinates are None
                    self.original_locations.append((None, None))
                    self.anonymized_locations.append((None, None))
            else:
                # Handle case where coordinates don't exist
                self.original_locations.append((None, None))
                self.anonymized_locations.append((None, None))

            anonymized_locations.append(new_location)

        return anonymized_locations

    def create_visualization(self, output_path: str = None):
        """
        Create a before/after visualization of the location anonymization.
        """
        if not self.original_locations or not self.anonymized_locations or self.home_location is None:
            print("Cannot create visualization: missing location data or home location")
            return

        # Filter out None coordinates
        orig_coords = [(lat, lon) for lat, lon in self.original_locations if lat is not None and lon is not None]
        anon_coords = [(lat, lon) for lat, lon in self.anonymized_locations if lat is not None and lon is not None]

        if not orig_coords:
            print("No valid coordinates found for visualization")
            return

        # Create figure with subplots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

        # Calculate zoom area around home (±2km)
        zoom_radius = 2.0  # km
        lat_offset = zoom_radius / 111.32
        lon_offset = zoom_radius / (111.32 * math.cos(math.radians(self.home_location[0])))

        # Original locations plot
        orig_lats, orig_lons = zip(*orig_coords)
        ax1.scatter(orig_lons, orig_lats, c='blue', alpha=0.6, s=20, label='Location Points')
        ax1.scatter(self.home_location[1], self.home_location[0], c='red', s=200, marker='*',
                    label='Home Location', edgecolors='black', linewidth=2)

        ax1.set_xlim(self.home_location[1] - lon_offset, self.home_location[1] + lon_offset)
        ax1.set_ylim(self.home_location[0] - lat_offset, self.home_location[0] + lat_offset)
        ax1.set_xlabel('Longitude')
        ax1.set_ylabel('Latitude')
        ax1.set_title('Original Location Data\n(Centered on Home)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Add anonymization radius circle
        circle1 = plt.Circle((self.home_location[1], self.home_location[0]),
                             self.anonymization_radius_km / (111.32 * math.cos(math.radians(self.home_location[0]))),
                             fill=False, color='orange', linestyle='--', linewidth=2,
                             label=f'Anonymization Radius ({self.anonymization_radius_km}km)')
        ax1.add_patch(circle1)

        # Anonymized locations plot
        anon_lats, anon_lons = zip(*anon_coords)
        ax2.scatter(anon_lons, anon_lats, c='green', alpha=0.6, s=20, label='Anonymized Points')

        # Calculate anonymized home location
        anon_home_lat, anon_home_lon = self.anonymize_coordinates(self.home_location[0], self.home_location[1])
        ax2.scatter(anon_home_lon, anon_home_lat, c='red', s=200, marker='*',
                    label='Anonymized Home', edgecolors='black', linewidth=2)

        ax2.set_xlim(anon_home_lon - lon_offset, anon_home_lon + lon_offset)
        ax2.set_ylim(anon_home_lat - lat_offset, anon_home_lat + lat_offset)
        ax2.set_xlabel('Longitude')
        ax2.set_ylabel('Latitude')
        ax2.set_title('Anonymized Location Data\n(Shifted & Noised)')
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # Add anonymization radius circle to anonymized plot
        circle2 = plt.Circle((anon_home_lon, anon_home_lat),
                             self.anonymization_radius_km / (111.32 * math.cos(math.radians(anon_home_lat))),
                             fill=False, color='orange', linestyle='--', linewidth=2,
                             label=f'Anonymization Radius ({self.anonymization_radius_km}km)')
        ax2.add_patch(circle2)

        # Add statistics
        stats_text = f"""
        Anonymization Statistics:
        • Total locations: {len(orig_coords)}
        • Anonymization radius: {self.anonymization_radius_km} km
        • Noise factor: {self.noise_factor}
        • Global offset: {abs(self.coordinate_offset[0] * 111.32):.2f}km lat, {abs(self.coordinate_offset[1] * 111.32 * math.cos(math.radians(self.home_location[0]))):.2f}km lon
        """

        fig.text(0.02, 0.02, stats_text, fontsize=10, verticalalignment='bottom',
                 bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.8))

        plt.tight_layout()

        if output_path:
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            print(f"Visualization saved to: {output_path}")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"location_anonymization_demo_{timestamp}.png"
            plt.savefig(filename, dpi=300, bbox_inches='tight')
            print(f"Visualization saved to: {filename}")

        plt.show()

    def verify_anonymization(self, original_data: Dict, anonymized_data: Dict) -> bool:
        """
        Verify that no original coordinates remain in the anonymized data.
        """
        if 'locations' not in original_data or 'locations' not in anonymized_data:
            return True

        original_locations = original_data['locations']
        anonymized_locations = anonymized_data['locations']

        if len(original_locations) != len(anonymized_locations):
            print("Warning: Location array lengths don't match!")
            return False

        matches_found = 0
        for i, (orig_loc, anon_loc) in enumerate(zip(original_locations, anonymized_locations)):
            if 'latitude' in orig_loc and 'longitude' in orig_loc and 'latitude' in anon_loc and 'longitude' in anon_loc:
                orig_lat, orig_lon = orig_loc['latitude'], orig_loc['longitude']
                anon_lat, anon_lon = anon_loc['latitude'], anon_loc['longitude']

                if (orig_lat is not None and orig_lon is not None and
                        anon_lat is not None and anon_lon is not None):
                    # Check if coordinates are identical (should never happen after anonymization)
                    if abs(orig_lat - anon_lat) < 1e-10 and abs(orig_lon - anon_lon) < 1e-10:
                        matches_found += 1

        if matches_found > 0:
            print(f"⚠️  WARNING: Found {matches_found} locations with unchanged coordinates!")
            return False
        else:
            print(
                f"✅ VERIFICATION PASSED: All {len([loc for loc in self.original_locations if loc[0] is not None])} coordinates successfully anonymized")
            return True

    def anonymize_data(self, data: Dict) -> Dict:
        """
        Anonymize only the locations array in the dataset.
        Output JSON will be identical to input but with COMPLETELY REPLACED anonymized coordinates.
        """
        # Find home location first
        self.home_location = self.find_home_location(data)

        if self.home_location is None:
            print("Cannot proceed without home location. Returning original data.")
            return data

        # Generate global coordinate offset
        self.coordinate_offset = self.generate_coordinate_offset()
        print(f"Applying global coordinate offset: {self.coordinate_offset[0]:.6f}°, {self.coordinate_offset[1]:.6f}°")

        # Create anonymized copy of data (starts as identical structure)
        anonymized_data = copy.deepcopy(data)

        # Clear previous location data for visualization
        self.original_locations = []
        self.anonymized_locations = []

        # Anonymize only the locations array - COMPLETELY REPLACING original coordinates
        if 'locations' in anonymized_data:
            print(f"Anonymizing {len(anonymized_data['locations'])} location records...")
            print("⚠️  Original coordinates will be COMPLETELY REPLACED with anonymized versions")

            # Replace the entire locations array with anonymized version
            anonymized_data['locations'] = self.anonymize_locations_array(anonymized_data['locations'])

            # Verify that no original coordinates remain
            self.verify_anonymization(data, anonymized_data)

            # Calculate statistics
            valid_locations = len([loc for loc in self.original_locations if loc[0] is not None])
            near_home_count = 0

            for lat, lon in self.original_locations:
                if lat is not None and lon is not None:
                    distance = self.haversine_distance(lat, lon, self.home_location[0], self.home_location[1])
                    if distance <= self.anonymization_radius_km:
                        near_home_count += 1

            print(f"✓ Processed {valid_locations} valid location points")
            print(f"✓ {near_home_count} points within anonymization radius received extra noise")
        else:
            print("No 'locations' array found in the data")

        print("🔒 Anonymization complete! Output contains ONLY anonymized coordinates.")
        return anonymized_data


def main():
    parser = argparse.ArgumentParser(description='Anonymize location data in JSON file (locations array only)')
    parser.add_argument('input_file', help='Input JSON file path')
    parser.add_argument('output_file', help='Output JSON file path')
    parser.add_argument('home_activity_id', help='Primary activity ID that identifies home location')
    parser.add_argument('--radius', type=float, default=0.5, help='Anonymization radius in km (default: 0.5)')
    parser.add_argument('--noise', type=float, default=0.3, help='Noise factor 0.1-1.0 (default: 0.3)')
    parser.add_argument('--viz', type=str, default=None, help='Path to save visualization image (optional)')
    parser.add_argument('--no-viz', action='store_true', help='Skip creating visualization')

    args = parser.parse_args()

    # Load input data
    print(f"Loading data from {args.input_file}...")
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Input file '{args.input_file}' not found.")
        return
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}")
        return

    # Create anonymizer and process data
    anonymizer = LocationAnonymizer(
        home_primary_activity_id=args.home_activity_id,
        anonymization_radius_km=args.radius,
        noise_factor=args.noise
    )

    anonymized_data = anonymizer.anonymize_data(data)

    # Save anonymized data
    print(f"Saving anonymized data to {args.output_file}...")
    try:
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(anonymized_data, f, indent=2, ensure_ascii=False)
        print("✓ Anonymized data saved successfully!")
    except IOError as e:
        print(f"Error: Could not write to output file: {e}")
        return

    # Create visualization unless disabled
    if not args.no_viz:
        print("\nCreating before/after visualization...")
        try:
            anonymizer.create_visualization(args.viz)
        except ImportError:
            print("Warning: matplotlib not available. Install with: pip install matplotlib")
        except Exception as e:
            print(f"Warning: Could not create visualization: {e}")


if __name__ == "__main__":
    main()