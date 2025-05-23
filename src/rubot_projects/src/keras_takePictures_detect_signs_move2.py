#!/usr/bin/env python
import rospy
from sensor_msgs.msg import Image
from std_msgs.msg import String, Bool
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from cv_bridge import CvBridge, CvBridgeError
import cv2
import numpy as np
from tensorflow.keras.models import load_model
import time
from datetime import datetime
import os
import threading


class ImageClassifierNode:
    def __init__(self):
        rospy.loginfo("Inicializando nodo de clasificación de imágenes...")

        script_dir = os.path.dirname(os.path.realpath(__file__))
        model_path = os.path.join(script_dir, "../models/keras_model.h5")
        labels_path = os.path.join(script_dir, "../models/labels.txt")

        self.model = load_model(model_path)
        self.labels = self.load_labels(labels_path)
        self.input_shape = self.model.input_shape[1:3]

        self.bridge = CvBridge()
        self.image_sub = rospy.Subscriber("/usb_cam/image_raw", Image, self.image_callback, queue_size=1)
        self.class_pub = rospy.Publisher("/predicted_class", String, queue_size=1)
        rospy.Subscriber("/capture_toggle", Bool, self.toggle_callback)

        self.capture_enabled = True
        self.capture_dir = os.path.expanduser("~/rUBot_mecanum_ws/src/rubot_projects/rUBot_captures")
        os.makedirs(self.capture_dir, exist_ok=True)
        self.create_class_dirs()
        self.last_capture_time = time.time()
        self.capture_interval = 1.0

        self.image_count = 0
        self.debug_interval = 10

        rospy.loginfo("Nodo de clasificación de imágenes listo. Esperando imágenes...")

    def load_labels(self, path):
        with open(path, 'r') as f:
            return [line.strip().split(' ', 1)[1] for line in f.readlines()]

    def create_class_dirs(self):
        for class_name in self.labels:
            os.makedirs(os.path.join(self.capture_dir, class_name), exist_ok=True)

    def toggle_callback(self, msg):
        self.capture_enabled = msg.data
        state = "ACTIVADA" if self.capture_enabled else "DESACTIVADA"
        rospy.loginfo(f"[Clasificador] Captura automática {state}")

    def image_callback(self, msg):
        self.image_count += 1
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            resized = cv2.resize(cv_image, self.input_shape)
            img = resized.astype(np.float32) / 255.0
            img = np.expand_dims(img, axis=0)

            predictions = self.model.predict(img)
            class_index = np.argmax(predictions)
            class_name = self.labels[class_index]
            confidence = predictions[0][class_index]

            if self.image_count % self.debug_interval == 0:
                rospy.loginfo(f"[Clasificador] Imagen #{self.image_count} - Clase: {class_name} ({confidence:.2f})")

            self.class_pub.publish(class_name)

        except CvBridgeError as e:
            rospy.logerr(f"[Clasificador] Error de CvBridge: {e}")
        except Exception as e:
            rospy.logerr(f"[Clasificador] Error procesando imagen: {e}")


class SignalBehaviorNode:
    def __init__(self):
        rospy.loginfo("Inicializando nodo de comportamiento reactivo...")

        self.robot_x = 0.0
        self.robot_y = 0.0
        self.current_command = "Nothing"
        self.command_lock = threading.Lock()

        self.cmd_vel_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=1)
        rospy.Subscriber("/odom", Odometry, self.odom_callback)
        rospy.Subscriber("/predicted_class", String, self.class_callback)

        # Hilo que mantiene el movimiento según la señal detectada
        self.control_thread = threading.Thread(target=self.motion_loop)
        self.control_thread.daemon = True
        self.control_thread.start()

        rospy.loginfo("Nodo de comportamiento reactivo listo.")

    def odom_callback(self, msg):
        self.robot_x = msg.pose.pose.position.x
        self.robot_y = msg.pose.pose.position.y

    def class_callback(self, msg):
        with self.command_lock:
            self.current_command = msg.data
            rospy.loginfo(f"[Comportamiento] Señal detectada: {self.current_command}")

    def motion_loop(self):
        rate = rospy.Rate(10)  # 10 Hz
        while not rospy.is_shutdown():
            twist = Twist()
            with self.command_lock:
                cmd = self.current_command

            if cmd in ["Stop", "Give_Way"]:
                twist.linear.x = 0.0
                twist.angular.z = 0.0
                rospy.loginfo_throttle(2.0, f"[Comportamiento] Acción: PARAR por señal '{cmd}'")
            elif cmd == "Turn_Left":
                twist.linear.x = 0.0
                twist.angular.z = 0.5
                rospy.loginfo_throttle(2.0, f"[Comportamiento] Acción: GIRAR IZQUIERDA")
            elif cmd == "Turn_Right":
                twist.linear.x = 0.0
                twist.angular.z = -0.5
                rospy.loginfo_throttle(2.0, f"[Comportamiento] Acción: GIRAR DERECHA")
            elif cmd == "Nothing":
                twist.linear.x = 0.2
                twist.angular.z = 0.0
                rospy.loginfo_throttle(2.0, "[Comportamiento] Acción: AVANZAR (Nada detectado)")
            else:
                twist.linear.x = 0.0
                twist.angular.z = 0.0
                rospy.loginfo_throttle(2.0, f"[Comportamiento] Señal desconocida: '{cmd}'")

            self.cmd_vel_pub.publish(twist)
            rate.sleep()


if __name__ == "__main__":
    rospy.init_node("keras_takePictures_detect_signs_move2", anonymous=True)

    classifier_node = ImageClassifierNode()
    behavior_node = SignalBehaviorNode()

    rospy.loginfo("Sistema completo de clasificación y comportamiento iniciado.")
    rospy.spin()
