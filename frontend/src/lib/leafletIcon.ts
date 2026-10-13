// The default marker for every map: a brand-red dot drawn in CSS (.warn-pin
// in index.css). It replaces Leaflet's blue PNG pin, whose image URLs don't
// resolve under Vite and which cost three extra image requests per map.
// Importing this module for its side effect sets the default icon
// process-wide; shared by every map.
import L from "leaflet";

export const DefaultIcon = L.divIcon({
  className: "warn-pin",
  iconSize: [14, 14],
  iconAnchor: [7, 7],
  popupAnchor: [0, -8],
});

L.Marker.prototype.options.icon = DefaultIcon;
