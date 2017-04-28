"""Stationary obstacle model."""

import numpy as np
import pyproj
from auvsi_suas.models import distance
from auvsi_suas.models import units
from gps_position import GpsPosition
from django.conf import settings
from django.db import models

wgs84 = pyproj.Proj(init="epsg:4326")


class StationaryObstacle(models.Model):
    """A stationary obstacle that teams must avoid.

    Attributes:
        gps_position: The position of the obstacle center.
        cylinder_radius: The radius of the cylinder in feet.
        cylinder_height: The height of the cylinder in feet.
    """
    gps_position = models.ForeignKey(GpsPosition)
    cylinder_radius = models.FloatField()
    cylinder_height = models.FloatField()

    def __unicode__(self):
        """Descriptive text for use in displays."""
        return unicode("StationaryObstacle (pk:%s, radius:%s, height:%s, "
                       "gps:%s)" % (str(self.pk), str(self.cylinder_radius),
                                    str(self.cylinder_height),
                                    self.gps_position.__unicode__()))

    def determine_interpolated_collision(self, start_log, end_log, utm):
        """Determines whether the UAS collided with the obstacle by
        interpolating between start and end telemetry.

        Args:
            start_log: A UAS telemetry log.
            end_log: A UAS telemetry log.
            utm: The UTM Proj projection to project into.
        Returns:
            True if the UAS collided with the obstacle, False otherwise.
        """
        lat1 = start_log.uas_position.gps_position.latitude
        lon1 = start_log.uas_position.gps_position.longitude
        alt1 = start_log.uas_position.altitude_msl

        lat2 = end_log.uas_position.gps_position.latitude
        lon2 = end_log.uas_position.gps_position.longitude
        alt2 = end_log.uas_position.altitude_msl

        latc = self.gps_position.latitude
        lonc = self.gps_position.longitude

        # Don't interpolate if telemetry data is too sparse or the aircraft
        # velocity is above the bound.
        d = start_log.uas_position.distance_to(end_log.uas_position)
        t = (end_log.timestamp - start_log.timestamp).total_seconds()
        if (t > settings.MAX_TELMETRY_INTERPOLATE_INTERVAL_SEC or
            (d / t) > settings.MAX_AIRSPEED_FT_PER_SEC):
            # In this case, a collision exists if the UAS could go from
            # start_log to the obstacle to the end_log while remaining under
            # the velocity bound. The point in the obstacle we use is
            # self.gps_position with the altitude set to the mean of start_log
            # and end_log altitudes (as long as that is within
            # self.cylinder_height).
            optimal_alt = min(np.mean([alt1, alt2]), self.cylinder_height)
            start_to_obst = distance.distance_to(lat1, lon1, alt1, latc, lonc,
                                                 optimal_alt)
            obst_to_end = distance.distance_to(latc, lonc, optimal_alt, lat2,
                                               lon2, alt2)
            avg_velocity = (start_to_obst + obst_to_end) / t
            return avg_velocity <= settings.MAX_AIRSPEED_FT_PER_SEC

        # We want to check if the line drawn between start_log and end_log
        # ever crosses the obstacle.
        # We do this by looking at only the x, y dimensions and checking if the
        # 2d line intersects with the circle (cylindrical obstacle
        # cross-section). We then use the line equation to determine the
        # altitude at which the intersection occurs. If the altitude is between
        # 0 and self.cylinder_height, a collision occured.
        # Reference: https://math.stackexchange.com/questions/980089/how-to-check-if-a-3d-line-segment-intersects-a-cylinder

        # Convert points to UTM projection.
        # We need a cartesian coordinate system to perform the calculation.
        try:
            x1, y1 = pyproj.transform(wgs84, utm, lon1, lat1)
            z1 = units.feet_to_meters(alt1)
            x2, y2 = pyproj.transform(wgs84, utm, lon2, lat2)
            z2 = units.feet_to_meters(alt2)
            cx, cy = pyproj.transform(wgs84, utm, lonc, latc)
        except RuntimeError:
            # pyproj throws RuntimeError if the coordinates are grossly beyond
            # the bounds of the projection. We do not count this as a collision.
            return False

        # Calculate slope and intercept of line between start_log and end_log.
        m = (y2 - y1) / (x2 - x1)
        b = y1 - m * x1

        # Equation of obstacle circle: latc^2 + laty^2 = self.cylinder_radius^2
        # Substitute in line equation and solve for x.
        p = [m**2 + 1, 2 * m * b, b**2 - self.cylinder_radius**2]
        roots = np.roots(p)

        for root in roots:
            # Solve for altitude and check if within bounds.
            zcalc = ((root - x1) * (z2 - z1) / (x2 - x1)) + z1
            if (zcalc > 0 and zcalc < self.cylinder_height):
                return True
        return False

    def contains_pos(self, aerial_pos):
        """Whether the pos is contained within the obstacle.

        Args:
            aerial_pos: The AerialPosition to test.
        Returns:
            Whether the given position is inside the obstacle.
        """
        # Check altitude of position
        aerial_alt = aerial_pos.altitude_msl
        if (aerial_alt < 0 or aerial_alt > self.cylinder_height):
            return False
        # Check lat/lon of position
        dist_to_center = self.gps_position.distance_to(aerial_pos.gps_position)
        if dist_to_center > self.cylinder_radius:
            return False
        # Both within altitude and radius bounds, inside cylinder
        return True

    def evaluate_collision_with_uas(self, uas_telemetry_logs):
        """Evaluates whether the Uas logs indicate a collision.

        Args:
            uas_telemetry_logs: A list of UasTelemetry logs sorted by timestamp
                for which to evaluate.
        Returns:
            Whether a UAS telemetry log reported indicates a collision with the
            obstacle.
        """
        zone, north = distance.utm_zone(self.gps_position.latitude,
                                        self.gps_position.longitude)
        utm = distance.proj_utm(zone, north)
        for i in range(0, len(uas_telemetry_logs)):
            cur_log = uas_telemetry_logs[i]
            if i > 0:
                cur_log = uas_telemetry_logs[i]
                prev_log = uas_telemetry_logs[i - 1]
                if self.determine_interpolated_collision(
                        uas_telemetry_logs[i - 1], uas_telemetry_logs[i], utm):
                    return True
            else:
                if self.contains_pos(cur_log.uas_position):
                    return True
        return False

    def json(self):
        """Obtain a JSON style representation of object."""
        if self.gps_position is None:
            latitude = 0
            longitude = 0
        else:
            latitude = self.gps_position.latitude
            longitude = self.gps_position.longitude

        data = {
            'latitude': latitude,
            'longitude': longitude,
            'cylinder_radius': self.cylinder_radius,
            'cylinder_height': self.cylinder_height
        }
        return data
