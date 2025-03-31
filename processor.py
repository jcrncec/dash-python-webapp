import os
import zipfile
import xml.etree.ElementTree as ET
import re
from datetime import datetime

def extract_kml_from_kmz(kmz_file, output_dir):
    with zipfile.ZipFile(kmz_file, 'r') as zip_ref:
        zip_ref.extractall(output_dir)
    kml_files = [filename for filename in os.listdir(output_dir) if filename.endswith('doc.kml')]
    return os.path.join(output_dir, kml_files[0])

def delete_files_in_folder(folder_path, extension=None):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path) and (extension is None or filename.endswith(extension)):
                os.unlink(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

def remove_cdata_from_kml(kml_file):
    with open(kml_file, 'r+', encoding='utf-8') as f:
        kml_content = f.read()

        while True:
            start_index = kml_content.find('<![CDATA[')
            end_index = kml_content.find(']]>', start_index) + len(']]>')
            if start_index != -1 and end_index != -1:
                kml_content = kml_content[:start_index] + kml_content[end_index:]
                f.seek(0)
                f.truncate()
                f.write(kml_content)
            else:
                break

        f.seek(0)
        content = f.read()
        filename = os.path.splitext(os.path.basename(kml_file))[0]
        first_part = filename.split('_')[0]
        content = content.replace('<name>NULL</name>', f'<name>{first_part}</name>')
        f.seek(0)
        f.truncate()
        f.write(content)

    return kml_file


def extract_coordinates_from_kml(kml_file, count, working_street_id):
    tree = ET.parse(kml_file)
    root = tree.getroot()

    for placemark in root.findall('.//{http://www.opengis.net/kml/2.2}Placemark'):
        for coords_element in placemark.findall('.//{http://www.opengis.net/kml/2.2}coordinates'):
            count += 1
            coords = coords_element.text.strip().split()
            output = 'insert into working_street_polygon (id,name,geom,working_street_id,active,company_id,created,created_user_id) values (uuid_generate_v1(), \'S' + str(count) + '\' , \'POLYGON(('
            for coord in coords:
                parts = coord.split(',')
            if len(parts) >= 2:
                lon, lat = parts[0], parts[1]
                alt = parts[2] if len(parts) > 2 else '0'
                output += f"{lat} {lon},"
            output = output[:-1] + '))\',\'' + working_street_id + '\', TRUE, \'ZG_PARKIS\', NOW(), \'10fe9397-13da-4ddf-8d50-ef0a83313bb2\');'
            print(output)
    return count

def merge_kml_files(input_folder, output_file, count):
    merged_root = ET.Element('kml')
    merged_document = ET.SubElement(merged_root, 'Document')

    for filename in os.listdir(input_folder):
        if filename.endswith('.kml'):
            file_path = os.path.join(input_folder, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                kml_tree = ET.parse(f)
                kml_root = kml_tree.getroot()

                for placemark in kml_root.findall('.//{http://www.opengis.net/kml/2.2}Placemark'):
                    count += 1
                    placemark.set('id', 'S' + str(count))
                    if 'id' in placemark.attrib:
                        del placemark.attrib['id']

                    name_element = placemark.find('{http://www.opengis.net/kml/2.2}name')
                    if name_element is not None:
                        name_element.text = f'S{count} ' + name_element.text

                    extended_data = placemark.find('{http://www.opengis.net/kml/2.2}ExtendedData')
                    if extended_data is not None:
                        valueExt = extended_data.find(".//Data[@name='Area ID']/value")
                        print(valueExt)

                    for tag in ['snippet', 'description']:
                        element = placemark.find(f'{{http://www.opengis.net/kml/2.2}}{tag}')
                        if element is not None:
                            placemark.remove(element)

                    style_url_element = placemark.find('{http://www.opengis.net/kml/2.2}styleUrl')
                    if style_url_element is not None and style_url_element.text == '#PolyStyle00':
                        style_url_element.text = '#styleMap-01'

                    multi_geometry = placemark.find('{http://www.opengis.net/kml/2.2}MultiGeometry')
                    if multi_geometry is not None:
                        polygon = multi_geometry.find('{http://www.opengis.net/kml/2.2}Polygon')
                        if polygon is not None:
                            tessellate_element = ET.SubElement(polygon, 'tessellate')
                            tessellate_element.text = '1'
                            for tag in ['altitudeMode', 'extrude']:
                                element = polygon.find(f'{{http://www.opengis.net/kml/2.2}}{tag}')
                                if element is not None:
                                    polygon.remove(element)

                    extra_data = ET.SubElement(placemark, 'ExtendedData')
                    data_elements = [
                        ('Color', '000000FF'),
                        ('ID', name_element.text if name_element is not None else ''),
                        ('OriginalName', ''),
                        ('ImportOrigin', ''),
                        ('ImportCreatedTime', ''),
                        ('ImportModifiedTime', ''),
                        ('Checked', 'False'),
                        ('LastEditTime', datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
                        ('LastEditUser', 'RAO'),
                        ('ParkingType', 'Parallel'),
                        ('Capacity', '1'),
                        ('CalculatedCapacity', ''),
                        ('UserCapacity', '1'),
                        ('ParkingPolicy', 'DEFAULT'),
                        ('InactiveFrom', ''),
                        ('InactiveTo', ''),
                        ('PointCount', '4'),
                        ('CollectionId', ''),
                        ('CollectionPoints', ''),
                        ('WSID', ''),
                        ('Regime:Default', 'DEFAULT')
                    ]
                    for name, value in data_elements:
                        data_element = ET.SubElement(extra_data, 'Data', attrib={'name': name})
                        value_element = ET.SubElement(data_element, 'value')
                        value_element.text = value

                    merged_document.append(placemark)

    ET.register_namespace('', "http://www.opengis.net/kml/2.2")
    merged_tree = ET.ElementTree(merged_root)
    merged_tree.write(output_file, encoding='utf-8', xml_declaration=True)
